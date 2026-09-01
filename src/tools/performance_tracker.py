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

from utils.data import BQ as client
from utils.data import (
    DISOWNED_COHORT_NOTE,
    FORWARD_PAPER_LEDGER,
    LIVE_COHORT_NOTE,
    LIVE_COHORT_START_DATE,
    LIVE_POLICY_VERSION,
    SIGNAL_PERFORMANCE_TABLE,
)
from utils.safety import clamp, safe_error

logger = logging.getLogger(__name__)

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
        {universe, basis, note, row_count, matched_rows, truncated,
         rows: [{ticker, direction, score, entry_price, current_price,
         underlying_pct_change, underlying_direction_outcome, scan_date}]} —
         field names carry the universe on purpose. Check `truncated` before
         computing any statistic: the cap cuts mid-scan_date on score.
    """
    if not client:
        return {"error": "BigQuery client not initialized"}

    limit = clamp(limit, 1, 50, default=50)

    try:
        # scan_date is STRING in this table
        base_query = f"""
            SELECT
                ticker, direction, signal_score as score, signal_price as entry_price, current_price,
                pct_change as pnl_pct, is_win, scan_date
            FROM {SIGNAL_PERFORMANCE_TABLE}
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

        # How many rows the filters actually match, BEFORE the cap. Without
        # this the caller gets N rows and cannot tell N was the whole answer or
        # the top of a longer one. The sort is `scan_date DESC, score DESC`, so
        # a truncated response ends mid-scan_date on SCORE: its oldest date is a
        # highest-score-only slice, and any statistic over it is biased upward.
        # Same defect class as the 200-row query_outcomes truncation.
        count_query = (
            "SELECT COUNT(*) AS n FROM ("
            + base_query
            + ")"
        )
        matched_rows = None
        try:
            matched_rows = next(
                iter(
                    client.query(
                        count_query,
                        job_config=bigquery.QueryJobConfig(query_parameters=query_params),
                    ).result()
                )
            )["n"]
        except Exception:  # noqa: BLE001 — explanatory, never fatal
            matched_rows = None

        base_query += " ORDER BY scan_date DESC, score DESC LIMIT @limit"
        query_params.append(bigquery.ScalarQueryParameter("limit", "INTEGER", limit))

        job_config = bigquery.QueryJobConfig(query_parameters=query_params)
        query_job = client.query(base_query, job_config=job_config)

        rows = []
        for row in query_job.result():
            r = dict(row)
            # TF-03: universe lives in the field names themselves — a row
            # copied out of context still says "underlying", not "pnl".
            is_win = r.pop("is_win", None)
            r["underlying_pct_change"] = r.pop("pnl_pct", None)
            # NULL is_win = tracking not yet resolved — never fabricate a LOSS.
            if is_win is None:
                r["underlying_direction_outcome"] = "UNRESOLVED"
            else:
                r["underlying_direction_outcome"] = "WIN" if is_win else "LOSS"
            rows.append(r)

        truncated = bool(matched_rows is not None and matched_rows > len(rows))
        note = _UNDERLYING_UNIVERSE_NOTE
        if truncated:
            note += (
                f" TRUNCATED: {matched_rows} rows match these filters and {len(rows)} "
                "were returned, ordered scan_date DESC then score DESC. The OLDEST "
                "scan_date in this response is therefore a highest-score-only slice, "
                "not that whole date. Do NOT compute a statistic over these rows: "
                "narrow scan_date or raise limit until truncated is false."
            )
        elif matched_rows is None:
            note += (
                " Could not determine whether this response is complete (the row "
                "count failed). Treat it as possibly truncated."
            )
        return {
            "universe": "underlying_direction",
            "basis": "UNDERLYING-STOCK DIRECTION — NOT option PnL",
            "note": note,
            "row_count": len(rows),
            "matched_rows": matched_rows,
            "truncated": truncated,
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

    There is deliberately NO bare `win_rate` field in the response: the
    headline is `underlying_direction_win_rate` (and bull_/bear_ variants),
    so the number cannot be quoted without its universe.

    Args:
        days: Lookback period in days (default 30).

    Returns:
        Summary statistics object with universe/basis markers;
        underlying_direction_win_rate is the headline metric.
    """
    if not client:
        return {"error": "BigQuery client not initialized"}

    days = clamp(days, 1, 365, default=30)

    try:
        # Calculate start date based on days lookback
        # scan_date is STRING, so we use PARSE_DATE
        # Direction comparisons use UPPER() so the aggregation is casing-tolerant
        # against any schema drift in the signal_performance table.
        query = f"""
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
                FROM {SIGNAL_PERFORMANCE_TABLE}
                WHERE PARSE_DATE('%Y-%m-%d', scan_date) >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
            ),
            best_ticker AS (
                SELECT ticker, AVG(pct_change) as avg_pnl
                FROM {SIGNAL_PERFORMANCE_TABLE}
                WHERE PARSE_DATE('%Y-%m-%d', scan_date) >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
                GROUP BY ticker
                ORDER BY avg_pnl DESC
                LIMIT 1
            ),
            worst_ticker AS (
                SELECT ticker, AVG(pct_change) as avg_pnl
                FROM {SIGNAL_PERFORMANCE_TABLE}
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

        raw = {}
        for row in query_job.result():
            raw = dict(row)
            break

        if not raw:
            return {"message": "No performance data found for this period"}

        # TF-01: the bare `win_rate`/`bull_win_rate`/`bear_win_rate` keys are
        # deliberately GONE. A caller grabbing "win_rate" here read 81% while
        # the option-PnL receipts said 33% — same word, different universe.
        # The response is rebuilt explicitly so no ambiguous key can leak
        # through from the query row.
        total = raw.get("total_signals", 0) or 0
        result: dict[str, Any] = {
            "universe": "underlying_direction",
            "basis": "UNDERLYING-STOCK DIRECTION — NOT option PnL",
            "note": _UNDERLYING_UNIVERSE_NOTE,
            "total_signals": total,
            "wins": raw.get("wins", 0),
            "underlying_direction_win_rate": (
                round((raw.get("wins", 0) / total) * 100, 2) if total > 0 else 0.0
            ),
            "avg_underlying_return": raw.get("avg_return"),
            "max_underlying_return": raw.get("max_return"),
            "min_underlying_return": raw.get("min_return"),
            "best_performer": raw.get("best_performer"),
            "worst_performer": raw.get("worst_performer"),
        }

        bull_total = raw.get("bull_total", 0) or 0
        result["bull_total"] = bull_total
        if bull_total > 0:
            result["bull_underlying_direction_win_rate"] = round(
                (raw.get("bull_wins", 0) / bull_total) * 100, 2
            )

        bear_total = raw.get("bear_total", 0) or 0
        result["bear_total"] = bear_total
        if bear_total > 0:
            result["bear_underlying_direction_win_rate"] = round(
                (raw.get("bear_wins", 0) / bear_total) * 100, 2
            )

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
    selection. No-trade days are reported separately in `skip_days` (they are
    part of the honest track record); invalid-liquidity rows are excluded.

    Live policy (`V7_1_TILTED_GIGO`, cohort since 2026-08-21, the
    PRINT_FLOOR_MIN=25 reset — engine decision
    docs/DECISIONS/2026-08-20-score-floor-accepted-print-floor-25-shipped.md):
    enter 10:00 ET
    the day after scan, +40% target / -30% stop, flat 15:45 ET same day.
    Earlier policy_version cohorts used different exits AND include cohorts the
    engine has since repudiated — do not mix cohorts
    when computing aggregates.

    Args:
        days: Lookback window in days (default 30, clamped 1-365).
        limit: Max rows (default 50, clamped 1-200).
        policy_version: Cohort filter (default = the live cohort, which is the
            PAIR of policy label AND entry >= LIVE_COHORT_START_DATE — the
            label alone does not define it). Pass "all" to reach every era, but
            "all" includes cohorts the engine has REPUDIATED, not merely
            different exit mechanics; it is not a track record.

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
        query = f"""
            SELECT
                scan_date, ticker, direction, recommended_contract,
                entry_price, target_price, stop_price,
                realized_return_pct, exit_reason,
                underlying_entry_price, underlying_exit_price, underlying_return,
                spy_return_over_window,
                entry_timestamp, exit_timestamp, policy_version
            FROM {FORWARD_PAPER_LEDGER}
            WHERE exit_timestamp IS NOT NULL
              AND DATE(exit_timestamp, 'America/New_York') < CURRENT_DATE('America/New_York')
              AND entry_price IS NOT NULL
              AND exit_reason NOT IN ("INVALID_LIQUIDITY", "SKIPPED")
              AND scan_date >= DATE_SUB(CURRENT_DATE('America/New_York'), INTERVAL @days DAY)
              AND IFNULL(is_skipped, FALSE) = FALSE
        """
        query_params = [
            bigquery.ScalarQueryParameter("days", "INTEGER", days),
        ]
        cohort_floored = False
        # Normalize first (see historical.py): a case-variant of the live label
        # would otherwise skip the date floor and then match zero rows.
        pv = policy_version.strip() if policy_version else policy_version
        if pv and pv.casefold() == LIVE_POLICY_VERSION.casefold():
            pv = LIVE_POLICY_VERSION
        policy_version = pv
        if policy_version and policy_version.lower() != "all":
            query += " AND policy_version = @policy_version"
            query_params.append(
                bigquery.ScalarQueryParameter("policy_version", "STRING", policy_version)
            )
            # The policy label alone does NOT define the cohort — disowned
            # cohorts remain in the ledger under the same label (date-filter
            # resets since 2026-07-28). Floor the LIVE cohort by entry date.
            if policy_version == LIVE_POLICY_VERSION:
                query += " AND DATE(entry_timestamp, 'America/New_York') >= @cohort_start"
                query_params.append(
                    bigquery.ScalarQueryParameter("cohort_start", "DATE", LIVE_COHORT_START_DATE)
                )
                cohort_floored = True
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

        # Skip days are the honesty signal for fail-closed days (regime rail,
        # no candidates) — surface them alongside the trades, past days only.
        #
        # SAME-DAY GUARD (2026-08-07). `scan_date < CURRENT_DATE` was NOT
        # sufficient: the trader writes a skip row on the ENTRY morning, and
        # entry_day is the trading day AFTER scan_date. So a row with
        # scan_date = the previous trading day passes that test and reveals
        # that the engine is flat TODAY, at ~10:00 ET. That is a same-day read
        # on the operator's live position state. It is not a pick, so it never
        # breached the letter of the no-same-day-pick guarantee, but it leaks
        # the complement of one and it was an accident rather than a decision.
        #
        # Skip rows have no entry_timestamp to compare, and calendar-day
        # arithmetic breaks across weekends and holidays (a Friday scan's entry
        # is Monday). So gate on the LEDGER's own clock instead: the trader
        # writes a row every trading day, so MAX(scan_date) is always the scan
        # whose entry day is today. Showing strictly older scans hides exactly
        # today's state, with no trading calendar required. Before the trader
        # has run on a given day this is conservative by one session, which is
        # the safe direction.
        skip_query = f"""
            SELECT CAST(scan_date AS STRING) AS scan_date, skip_reason
            FROM {FORWARD_PAPER_LEDGER}
            WHERE IFNULL(is_skipped, FALSE) = TRUE
              AND scan_date < (SELECT MAX(scan_date) FROM {FORWARD_PAPER_LEDGER})
              AND scan_date >= DATE_SUB(CURRENT_DATE('America/New_York'), INTERVAL @days DAY)
        """
        skip_params = [bigquery.ScalarQueryParameter("days", "INTEGER", days)]
        if policy_version and policy_version.lower() != "all":
            skip_query += " AND policy_version = @policy_version"
            skip_params.append(
                bigquery.ScalarQueryParameter("policy_version", "STRING", policy_version)
            )
            if policy_version == LIVE_POLICY_VERSION:
                # Skipped rows have no entry_timestamp (no entry happened), so
                # the cohort floor lands on scan_date. That is conservative by
                # at most one boundary scan (the scan whose entry WOULD have
                # been cohort_start), which errs toward showing fewer skip days
                # rather than importing a disowned cohort's skips.
                skip_query += " AND scan_date >= @cohort_start"
                skip_params.append(
                    bigquery.ScalarQueryParameter("cohort_start", "DATE", LIVE_COHORT_START_DATE)
                )
        skip_query += " ORDER BY scan_date DESC LIMIT 100"
        skip_days = [
            dict(row)
            for row in client.query(
                skip_query, job_config=bigquery.QueryJobConfig(query_parameters=skip_params)
            ).result()
        ]

        return {
            "policy_version": policy_version or "all",
            "cohort_start": LIVE_COHORT_START_DATE if cohort_floored else None,
            "row_count": len(rows),
            "rows": rows,
            "skip_days": skip_days,
            "note": (
                "Realized rows only (exit strictly before today, ET). "
                "realized_return_pct is a FRACTION of entry premium. skip_days "
                "lists no-trade days (fail-closed regime rail, no candidates) — "
                "they are part of the honest track record. "
                + (
                    f"{LIVE_COHORT_NOTE} A row_count of 0 means the cohort has "
                    "not accrued closed trades yet, NOT that there is no track "
                    "record. skip_days is floored on scan_date, so it begins one "
                    "session after cohort_start — do not use it as the "
                    "cohort's trading-day denominator on day one."
                    if cohort_floored
                    else DISOWNED_COHORT_NOTE
                )
            ),
        }

    except Exception as e:
        return {"error": safe_error(e, "get_position_history")}
