"""
Performance tracking tools for GammaRips MCP
"""

import logging
import os
from typing import Any

import httpx
from google.cloud import bigquery

logger = logging.getLogger(__name__)

# Initialize client
try:
    client = bigquery.Client(project="profitscout-fida8")
except Exception as e:
    logger.error(f"Failed to initialize BigQuery client: {e}")
    client = None

POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "").strip() or None


def _polygon_option_mid(contract: str) -> float | None:
    """Return the current mid price for a Polygon option contract (e.g.
    "O:FIX260515C01780000"). Returns None on any failure or when POLYGON_API_KEY
    is not mounted — callers must handle None gracefully."""
    if not POLYGON_API_KEY or not contract:
        return None
    try:
        # Underlying is embedded in the OCC-style contract; Polygon's
        # snapshot endpoint takes underlying + option symbol.
        # e.g. O:FIX260515C01780000 -> underlying "FIX"
        if contract.startswith("O:"):
            tail = contract[2:]
            # ticker chars until the first digit
            underlying = ""
            for ch in tail:
                if ch.isdigit():
                    break
                underlying += ch
        else:
            underlying = contract.split(":")[0]

        url = f"https://api.polygon.io/v3/snapshot/options/{underlying}/{contract}"
        resp = httpx.get(url, params={"apiKey": POLYGON_API_KEY}, timeout=5.0)
        resp.raise_for_status()
        data = resp.json().get("results") or {}
        lq = data.get("last_quote") or {}
        bid, ask = lq.get("bid"), lq.get("ask")
        if bid is not None and ask is not None and ask > 0:
            return round((bid + ask) / 2, 4)
        # Fallback to last trade if quote not available
        lt = data.get("last_trade") or {}
        price = lt.get("price")
        return float(price) if price is not None else None
    except Exception as e:
        logger.warning(f"Polygon option snapshot failed for {contract}: {e}")
        return None


def get_signal_performance(
    scan_date: str | None = None,
    ticker: str | None = None,
    direction: str | None = None,
    outcome: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """
    Track how signals actually performed against market outcomes.

    Args:
        scan_date: Filter by date (YYYY-MM-DD).
        ticker: Filter to specific ticker.
        direction: "bull" or "bear".
        outcome: "win" or "loss" to filter.
        limit: Max results (default 50).

    Returns:
        Performance records with: ticker, direction, score, entry_price, current_price, pnl_pct, outcome, scan_date.
    """
    if not client:
        return [{"error": "BigQuery client not initialized"}]

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

        results = []
        for row in query_job.result():
            r = dict(row)
            # Add 'outcome' string field for compatibility
            r["outcome"] = "WIN" if r.get("is_win") else "LOSS"
            results.append(r)

        return results

    except Exception as e:
        logger.error(f"Error in get_signal_performance: {e}")
        return [{"error": str(e)}]


def get_win_rate_summary(days: int = 30) -> dict[str, Any]:
    """
    Aggregate performance statistics.

    Args:
        days: Lookback period in days (default 30).

    Returns:
        Summary statistics object.
    """
    if not client:
        return {"error": "BigQuery client not initialized"}

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

        return result

    except Exception as e:
        logger.error(f"Error in get_win_rate_summary: {e}")
        return {"error": str(e)}


def get_open_position() -> dict[str, Any]:
    """
    Returns the current V5.3 trade status across three surfaces that together
    answer 'what trade am I in right now?' for a chat agent.

    IMPORTANT — the forward-paper-trader is a BATCH simulator that only writes
    ledger rows AFTER the 3-day hold window closes. There is no "currently-open
    position" in the ledger by design; every ledger row is terminal. Instead of
    inventing one, this tool returns three orthogonal pieces the chat agent can
    narrate:

      1. pending_pick — the signal-notifier's most recent decision from Firestore
         `todays_pick/{scan_date}`. This is the next trade that will be entered
         at 10:00 ET the following trading day (if has_pick=true), or a skip
         with reason if the V5.3 gates didn't clear.
      2. awaiting_simulation — scan_dates between the last simulated scan and
         today that are still inside their 3-day hold window and have NOT yet
         been reconciled into the ledger.
      3. most_recent_closed_trade — the latest ledger row with a real entry fill
         and a real exit. Gives the chat agent something concrete to reference
         when a user asks 'how did the last one do?'

    Returns:
        {
          "explanation": str,                    # plain-English summary the
                                                 # chat agent can paraphrase
          "pending_pick": {...} | None,          # from Firestore todays_pick
          "awaiting_simulation": [scan_date,...],# scan_dates still in hold
          "most_recent_closed_trade": {...} | None,
        }
    """
    if not client:
        return {"error": "BigQuery client not initialized"}

    result: dict[str, Any] = {
        "explanation": None,
        "pending_pick": None,
        "awaiting_simulation": [],
        "most_recent_closed_trade": None,
    }

    # --- 1. pending_pick from Firestore todays_pick/{latest scan_date} ---
    try:
        from google.cloud import firestore as _fs  # local to avoid hard coupling

        fs = _fs.Client(project="profitscout-fida8")
        docs = list(
            fs.collection("todays_pick")
            .order_by("scan_date", direction=_fs.Query.DESCENDING)
            .limit(1)
            .stream()
        )
        if docs:
            d = docs[0].to_dict() or {}
            for k, v in list(d.items()):
                if hasattr(v, "isoformat"):
                    d[k] = v.isoformat()
            result["pending_pick"] = d
    except Exception as e:
        logger.warning(f"pending_pick Firestore read failed: {e}")

    # --- 2. awaiting_simulation — scan_dates in enriched but not yet in ledger ---
    try:
        q = """
            WITH enriched_dates AS (
                SELECT DISTINCT scan_date
                FROM `profitscout-fida8.profit_scout.overnight_signals_enriched`
                WHERE scan_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 10 DAY)
            ),
            ledgered AS (
                SELECT DISTINCT scan_date
                FROM `profitscout-fida8.profit_scout.forward_paper_ledger`
                WHERE scan_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 10 DAY)
            )
            SELECT e.scan_date
            FROM enriched_dates e
            LEFT JOIN ledgered l USING (scan_date)
            WHERE l.scan_date IS NULL
            ORDER BY e.scan_date DESC
        """
        result["awaiting_simulation"] = [str(row.scan_date) for row in client.query(q).result()]
    except Exception as e:
        logger.warning(f"awaiting_simulation query failed: {e}")

    # --- 3. most_recent_closed_trade (real entry + real exit, V5.3 only) ---
    try:
        q = """
            SELECT
                scan_date, ticker, direction, recommended_contract,
                entry_price, target_price, stop_price,
                entry_timestamp, exit_timestamp,
                exit_reason, realized_return_pct,
                underlying_entry_price, underlying_exit_price,
                underlying_return, spy_return_over_window,
                policy_version
            FROM `profitscout-fida8.profit_scout.forward_paper_ledger`
            WHERE entry_price IS NOT NULL
              AND exit_timestamp IS NOT NULL
              AND exit_reason NOT IN ("INVALID_LIQUIDITY", "SKIPPED")
              AND policy_version = "V5_3_TARGET_80"
            ORDER BY exit_timestamp DESC
            LIMIT 1
        """
        for row in client.query(q).result():
            r = dict(row)
            for k, v in list(r.items()):
                if hasattr(v, "isoformat"):
                    r[k] = v.isoformat()
            result["most_recent_closed_trade"] = r
            break
    except Exception as e:
        logger.warning(f"most_recent_closed_trade query failed: {e}")

    # --- 4. narrative explanation for the chat agent ---
    parts = []
    pp = result["pending_pick"]
    if pp and pp.get("has_pick"):
        parts.append(
            f"Next trade: {pp.get('ticker')} {pp.get('direction')} "
            f"({pp.get('recommended_contract')}), entry at {pp.get('effective_at')}."
        )
    elif pp:
        parts.append(
            f"No next trade — {pp.get('skip_reason') or 'no pick'} for scan {pp.get('scan_date')}."
        )
    else:
        parts.append("No pending pick found in Firestore todays_pick.")

    if result["awaiting_simulation"]:
        parts.append(
            f"{len(result['awaiting_simulation'])} scan_date(s) awaiting simulator "
            f"reconciliation (within 3-day hold): {', '.join(result['awaiting_simulation'])}."
        )

    mr = result["most_recent_closed_trade"]
    if mr:
        parts.append(
            f"Last closed trade: {mr.get('ticker')} {mr.get('direction')} on "
            f"{mr.get('scan_date')} → {mr.get('exit_reason')} "
            f"at {mr.get('realized_return_pct')}%."
        )
    else:
        parts.append("No closed V5.3 trades yet in the ledger.")

    parts.append(
        "Reminder: the paper-trader is a batch simulator. There is no live "
        "open position in the ledger by design."
    )

    result["explanation"] = " ".join(parts)
    return result


def get_position_history(
    days: int = 30,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """
    Returns realized (closed) V5.3 paper trades from the last N days, row-level,
    for chat-agent answers like "show me recent wins/losses" or "how did FIX do".
    PIT-safe: only rows where exit_timestamp IS NOT NULL AND DATE(exit_timestamp)
    < today (no intraday-open rows).

    Args:
        days: Lookback window in trading-day-equivalents (default 30).
        limit: Max rows (default 50, clamped 1-200).

    Returns:
        List of {scan_date, ticker, direction, recommended_contract, entry_price,
                 exit_price, realized_return_pct, exit_reason, entry_timestamp,
                 exit_timestamp, policy_version}.
    """
    if not client:
        return [{"error": "BigQuery client not initialized"}]

    limit = max(1, min(int(limit), 200))

    try:
        # Columns verified against BQ INFORMATION_SCHEMA on 2026-04-20 — there is
        # no `exit_price` column; the ledger encodes outcome via realized_return_pct
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
            ORDER BY exit_timestamp DESC
            LIMIT @limit
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("days", "INTEGER", days),
                bigquery.ScalarQueryParameter("limit", "INTEGER", limit),
            ]
        )

        results = []
        for row in client.query(query, job_config=job_config).result():
            r = dict(row)
            for k, v in list(r.items()):
                if hasattr(v, "isoformat"):
                    r[k] = v.isoformat()
            results.append(r)
        return results

    except Exception as e:
        logger.error(f"Error in get_position_history: {e}")
        return [{"error": str(e)}]
