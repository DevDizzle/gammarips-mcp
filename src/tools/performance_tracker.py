"""
Performance tracking tools for GammaRips MCP.

Two DIFFERENT outcome universes live here — never conflate them:

  * `signal_performance` (get_signal_performance / get_win_rate_summary) —
    UNDERLYING-STOCK directional outcomes for the broad enriched pool
    (~30 signals/day, 3-day forward window). "Was the direction call right"
    — NOT option PnL. Direction being right (~54%) does not mean the option
    made money (~41%).
  * `forward_paper_ledger` (get_position_history) — the engine's realized
    OPTION paper trades: one tournament pick per day, simulated with real
    fills under the live bracket policy. These are the receipts.

V3 removed `get_open_position`: the engine's pending selection is not
published same-day. Only realized (closed) rows are served.
"""

import logging
from typing import Any

from google.cloud import bigquery

from utils.safety import clamp, safe_error

logger = logging.getLogger(__name__)

# Initialize client
try:
    client = bigquery.Client(project="profitscout-fida8")
except Exception as e:
    logger.error(f"Failed to initialize BigQuery client: {e}")
    client = None

# The live paper-cohort policy label. Earlier cohorts used different exit
# mechanics — mixing them in one aggregate produces nonsense.
LIVE_POLICY_VERSION = "V7_1_TILTED_GIGO"

_UNDERLYING_UNIVERSE_NOTE = (
    "UNDERLYING-STOCK directional outcomes (~30 enriched signals/day, 3-day "
    "forward window) — NOT option PnL. For realized option trades use "
    "get_position_history / get_historical_performance."
)


def get_signal_performance(
    scan_date: str | None = None,
    ticker: str | None = None,
    direction: str | None = None,
    outcome: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """
    UNDERLYING-STOCK directional outcomes for the broad enriched pool — did
    the direction call work on the stock over the 3-day forward window?

    This is NOT option PnL. On the same pool, the underlying moving the right
    way (~54%) does not mean the option made money (~41%) — theta, IV and the
    exit bracket eat the difference. For realized OPTION trades use
    `get_position_history`; for the full-pool option labels use
    `query_outcomes`.

    Args:
        scan_date: Filter by date (YYYY-MM-DD).
        ticker: Filter to specific ticker.
        direction: "bull" or "bear".
        outcome: "win" or "loss" to filter.
        limit: Max results (default 50).

    Returns:
        {universe, note, rows: [{ticker, direction, score, entry_price,
         current_price, pnl_pct, outcome, scan_date}]}
    """
    if not client:
        return {"error": "BigQuery client not initialized"}

    limit = clamp(limit, 1, 50, default=50)

    try:
        # scan_date is STRING in this table
        base_query = """
            SELECT
                ticker, direction, signal_score as score, signal_price as entry_price, current_price,
                pct_change as pnl_pct, is_win, scan_date
            FROM `profitscout-fida8.profit_scout.signal_performance`
            WHERE 1=1
        """

        query_params = []

        if scan_date:
            base_query += " AND scan_date = @scan_date"
            query_params.append(bigquery.ScalarQueryParameter("scan_date", "STRING", scan_date))

        if ticker:
            base_query += " AND ticker = @ticker"
            query_params.append(bigquery.ScalarQueryParameter("ticker", "STRING", ticker))

        if direction:
            # Prefix match — callers pass "bull"/"bear" but stored values are
            # "BULLISH"/"BEARISH". Exact LOWER()==LOWER() silently returned [].
            base_query += " AND LOWER(direction) LIKE LOWER(@direction) || '%'"
            query_params.append(bigquery.ScalarQueryParameter("direction", "STRING", direction))

        if outcome:
            # outcome 'win' -> is_win = TRUE, 'loss' -> is_win = FALSE
            is_win_val = outcome.lower() == "win"
            base_query += " AND is_win = @is_win"
            query_params.append(bigquery.ScalarQueryParameter("is_win", "BOOL", is_win_val))

        base_query += " ORDER BY scan_date DESC, score DESC LIMIT @limit"
        query_params.append(bigquery.ScalarQueryParameter("limit", "INTEGER", limit))

        job_config = bigquery.QueryJobConfig(query_parameters=query_params)
        query_job = client.query(base_query, job_config=job_config)

        rows = []
        for row in query_job.result():
            r = dict(row)
            # Add 'outcome' string field for compatibility
            r["outcome"] = "WIN" if r.get("is_win") else "LOSS"
            rows.append(r)

        return {
            "universe": "underlying_direction",
            "note": _UNDERLYING_UNIVERSE_NOTE,
            "row_count": len(rows),
            "rows": rows,
        }

    except Exception as e:
        return {"error": safe_error(e, "get_signal_performance")}


def get_win_rate_summary(days: int = 30) -> dict[str, Any]:
    """
    Aggregate UNDERLYING-STOCK direction statistics for the broad enriched
    pool over a lookback window.

    This win rate answers "how often was the direction call right on the
    STOCK" — it is NOT an option-PnL win rate and NOT the paper-trading track
    record. For those use `get_historical_performance` (realized option
    trades) or `get_outcome_summary` (full-pool option labels).

    Args:
        days: Lookback period in days (default 30).

    Returns:
        Summary statistics object with universe marker.
    """
    if not client:
        return {"error": "BigQuery client not initialized"}

    days = clamp(days, 1, 365, default=30)

    try:
        # Calculate start date based on days lookback
        # scan_date is STRING, so we use PARSE_DATE
        # Direction comparisons use UPPER() so the aggregation is casing-tolerant
        # against any schema drift in the signal_performance table.
        query = """
            WITH stats AS (
                SELECT
                    COUNT(*) as total_signals,
                    COUNTIF(is_win = TRUE) as wins,
                    AVG(pct_change) as avg_return,
                    COUNTIF(UPPER(direction) = 'BULLISH' AND is_win = TRUE) as bull_wins,
                    COUNTIF(UPPER(direction) = 'BULLISH') as bull_total,
                    COUNTIF(UPPER(direction) = 'BEARISH' AND is_win = TRUE) as bear_wins,
                    COUNTIF(UPPER(direction) = 'BEARISH') as bear_total,
                    MAX(pct_change) as max_return,
                    MIN(pct_change) as min_return
                FROM `profitscout-fida8.profit_scout.signal_performance`
                WHERE PARSE_DATE('%Y-%m-%d', scan_date) >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
            ),
            best_ticker AS (
                SELECT ticker, AVG(pct_change) as avg_pnl
                FROM `profitscout-fida8.profit_scout.signal_performance`
                WHERE PARSE_DATE('%Y-%m-%d', scan_date) >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
                GROUP BY ticker
                ORDER BY avg_pnl DESC
                LIMIT 1
            ),
            worst_ticker AS (
                SELECT ticker, AVG(pct_change) as avg_pnl
                FROM `profitscout-fida8.profit_scout.signal_performance`
                WHERE PARSE_DATE('%Y-%m-%d', scan_date) >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
                GROUP BY ticker
                ORDER BY avg_pnl ASC
                LIMIT 1
            )
            SELECT
                s.*,
                b.ticker as best_performer,
                w.ticker as worst_performer
            FROM stats s
            LEFT JOIN best_ticker b ON 1=1
            LEFT JOIN worst_ticker w ON 1=1
        """

        query_params = [bigquery.ScalarQueryParameter("days", "INTEGER", days)]

        job_config = bigquery.QueryJobConfig(query_parameters=query_params)
        query_job = client.query(query, job_config=job_config)

        result = {}
        for row in query_job.result():
            result = dict(row)
            break

        if not result:
            return {"message": "No performance data found for this period"}

        # Calculate percentages
        total = result.get("total_signals", 0)
        if total > 0:
            result["win_rate"] = round((result.get("wins", 0) / total) * 100, 2)
        else:
            result["win_rate"] = 0.0

        bull_total = result.get("bull_total", 0)
        if bull_total > 0:
            result["bull_win_rate"] = round((result.get("bull_wins", 0) / bull_total) * 100, 2)

        bear_total = result.get("bear_total", 0)
        if bear_total > 0:
            result["bear_win_rate"] = round((result.get("bear_wins", 0) / bear_total) * 100, 2)

        result["universe"] = "underlying_direction"
        result["underlying_direction_win_rate"] = result["win_rate"]
        result["note"] = _UNDERLYING_UNIVERSE_NOTE
        return result

    except Exception as e:
        return {"error": safe_error(e, "get_win_rate_summary")}


def get_position_history(
    days: int = 30,
    limit: int = 50,
    policy_version: str | None = LIVE_POLICY_VERSION,
) -> dict[str, Any]:
    """
    The RECEIPTS — realized (closed) paper trades from the engine's own daily
    selection, row-level. One tournament pick per day, simulated with real
    fills under the bracket policy live at the time.

    Realized-only by construction: rows appear only after the trade's exit,
    never same-day, so this tool cannot front-run the engine's private
    selection. Skip days and invalid-liquidity rows are excluded.

    Live policy (`V7_1_TILTED_GIGO`, cohort since 2026-06-26): enter 10:00 ET
    the day after scan, +40% target / -30% stop, flat 15:45 ET same day.
    Earlier policy_version cohorts used different exits — do not mix cohorts
    when computing aggregates.

    Args:
        days: Lookback window in days (default 30, clamped 1-365).
        limit: Max rows (default 50, clamped 1-200).
        policy_version: Cohort filter (default = the live cohort). Pass "all"
            to see every era — comparison across eras is on you.

    Returns:
        {policy_version, row_count, rows: [{scan_date, ticker, direction,
         recommended_contract, entry/target/stop prices, realized_return_pct,
         exit_reason, benchmarks, timestamps, policy_version}]}
    """
    if not client:
        return {"error": "BigQuery client not initialized"}

    days = clamp(days, 1, 365, default=30)
    limit = clamp(limit, 1, 200, default=50)

    try:
        # Columns verified against BQ INFORMATION_SCHEMA — there is no
        # `exit_price` column; the ledger encodes outcome via realized_return_pct
        # on the option premium and underlying_exit_price on the stock leg.
        # Also exclude INVALID_LIQUIDITY rows (contract had zero bars at 10:00 ET
        # day-1 so entry_price is NULL — these are terminal but uninformative).
        query = """
            SELECT
                scan_date, ticker, direction, recommended_contract,
                entry_price, target_price, stop_price,
                realized_return_pct, exit_reason,
                underlying_entry_price, underlying_exit_price, underlying_return,
                spy_return_over_window,
                entry_timestamp, exit_timestamp, policy_version
            FROM `profitscout-fida8.profit_scout.forward_paper_ledger`
            WHERE exit_timestamp IS NOT NULL
              AND DATE(exit_timestamp) < CURRENT_DATE()
              AND entry_price IS NOT NULL
              AND exit_reason NOT IN ("INVALID_LIQUIDITY", "SKIPPED")
              AND scan_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
              AND IFNULL(is_skipped, FALSE) = FALSE
        """
        query_params = [
            bigquery.ScalarQueryParameter("days", "INTEGER", days),
        ]
        if policy_version and policy_version.lower() != "all":
            query += " AND policy_version = @policy_version"
            query_params.append(
                bigquery.ScalarQueryParameter("policy_version", "STRING", policy_version)
            )
        query += """
            ORDER BY exit_timestamp DESC
            LIMIT @limit
        """
        query_params.append(bigquery.ScalarQueryParameter("limit", "INTEGER", limit))

        job_config = bigquery.QueryJobConfig(query_parameters=query_params)

        rows = []
        for row in client.query(query, job_config=job_config).result():
            r = dict(row)
            for k, v in list(r.items()):
                if hasattr(v, "isoformat"):
                    r[k] = v.isoformat()
            rows.append(r)
        return {
            "policy_version": policy_version or "all",
            "row_count": len(rows),
            "rows": rows,
            "note": (
                "Realized rows only (exit strictly before today). "
                "realized_return_pct is a FRACTION of entry premium. "
                "Paper-traded. Not investment advice."
            ),
        }

    except Exception as e:
        return {"error": safe_error(e, "get_position_history")}
