"""
Overnight Edge tools for GammaRips MCP.

Live-pool tools read the leakage-safe view `overnight_signals_enriched_safe`,
which physically strips the forward-outcome columns the win-tracker merges
back onto the raw enriched table (next_day_pct, day2/3_pct, peak_return_3d,
is_win, outcome_tier, ...). Agents therefore can never see a candidate's
future through these tools, on any historical date.

The same-day pick tools (get_todays_pick / list_todays_picks) were REMOVED in
V3: the engine's own daily selection is not published same-day. Realized
receipts remain available via get_position_history / get_historical_performance.
"""

import logging
from typing import Any

from google.cloud import bigquery

from utils.safety import clamp, safe_error

logger = logging.getLogger(__name__)

try:
    client = bigquery.Client(project="profitscout-fida8")
except Exception as e:
    logger.error(f"Failed to initialize BigQuery client: {e}")
    client = None

_SAFE_ENRICHED = "`profitscout-fida8.profit_scout.overnight_signals_enriched_safe`"
_RAW_SCAN = "`profitscout-fida8.profit_scout.overnight_signals`"


def get_overnight_signals(
    scan_date: str | None = None,
    direction: str | None = None,
    min_score: int = 0,
    ticker: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """
    Raw overnight scanner signals for a scan date — the wide net BEFORE
    curation. Use this to see where unusual options activity concentrated
    overnight across the full scan universe. The curated, enriched pool
    (what the engine actually works from) is `get_enriched_signals`.
    """
    if not client:
        return [{"error": "BigQuery client not initialized"}]

    limit = clamp(limit, 1, 50, default=50)
    min_score = clamp(min_score, 0, 10, default=0)

    try:
        # Determine scan_date if not provided
        if not scan_date:
            query = f"SELECT MAX(scan_date) as max_date FROM {_RAW_SCAN}"
            query_job = client.query(query)
            results = query_job.result()
            for row in results:
                scan_date = str(row.max_date) if row.max_date else None
                break

        if not scan_date:
            return [{"error": "No data found in overnight_signals table"}]

        # Build query
        # Mapping fields to expected output
        base_query = f"""
            SELECT
                ticker,
                direction,
                overnight_score as score,
                day_volume as volume,
                total_options_dollar_volume as premium,
                recommended_expiration as expiration,
                recommended_strike as strike,
                scan_date
            FROM {_RAW_SCAN}
            WHERE scan_date = @scan_date
        """

        query_params = [bigquery.ScalarQueryParameter("scan_date", "DATE", scan_date)]

        if direction:
            # Prefix match — callers pass "bull"/"bear" but stored values are
            # "BULLISH"/"BEARISH". Exact LOWER()==LOWER() silently returned [].
            base_query += " AND LOWER(direction) LIKE LOWER(@direction) || '%'"
            query_params.append(bigquery.ScalarQueryParameter("direction", "STRING", direction))

        if min_score > 0:
            base_query += " AND overnight_score >= @min_score"
            query_params.append(bigquery.ScalarQueryParameter("min_score", "INTEGER", min_score))

        if ticker:
            base_query += " AND ticker = @ticker"
            query_params.append(bigquery.ScalarQueryParameter("ticker", "STRING", ticker))

        base_query += " ORDER BY overnight_score DESC LIMIT @limit"
        query_params.append(bigquery.ScalarQueryParameter("limit", "INTEGER", limit))

        job_config = bigquery.QueryJobConfig(query_parameters=query_params)
        query_job = client.query(base_query, job_config=job_config)

        results = []
        for row in query_job.result():
            results.append(dict(row))

        # Convert date objects to strings for JSON serialization
        for r in results:
            if "scan_date" in r and r["scan_date"]:
                r["scan_date"] = str(r["scan_date"])
            if "expiration" in r and r["expiration"]:
                r["expiration"] = str(r["expiration"])

        return results

    except Exception as e:
        return [{"error": safe_error(e, "get_overnight_signals")}]


def get_enriched_signals(
    scan_date: str | None = None,
    direction: str | None = None,
    ticker: str | None = None,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """
    The curated candidate pool for a scan date — AI-enriched signals with
    news, technicals, catalyst context, a delta-targeted recommended contract,
    and (since 2026-06) the 60-day momentum feature `mom_60`.

    Enrichment gate: `overnight_score >= 4` AND directional UOA > $500K, then
    edge-ranked to the top ~50 BULLISH names. This is the pool the engine's
    own selection works from; your agent should treat it as the daily
    candidate set and reason to its OWN contract (see
    get_playbook("run-your-own-tournament")).

    Served from a leakage-safe view: forward-outcome columns are physically
    stripped, so historical dates can be queried without seeing the future.
    Liquidity caveat: `recommended_oi`/`recommended_volume` are scan-time
    snapshots, not live values; `recommended_spread_pct` is permanently NULL.
    """
    if not client:
        return [{"error": "BigQuery client not initialized"}]

    limit = clamp(limit, 1, 50, default=25)

    try:
        # Determine scan_date if not provided
        if not scan_date:
            query = f"SELECT MAX(scan_date) as max_date FROM {_SAFE_ENRICHED}"
            query_job = client.query(query)
            results = query_job.result()
            for row in results:
                scan_date = str(row.max_date) if row.max_date else None
                break

        if not scan_date:
            return [{"error": "No data found in the enriched signals view"}]

        # SELECT * is safe here BECAUSE this is the guarded view — the raw
        # table would leak win-tracker forward-outcome columns.
        base_query = f"""
            SELECT *
            FROM {_SAFE_ENRICHED}
            WHERE scan_date = @scan_date
        """

        query_params = [bigquery.ScalarQueryParameter("scan_date", "DATE", scan_date)]

        if direction:
            # Prefix match — callers pass "bull"/"bear" but stored values are
            # "BULLISH"/"BEARISH". Exact LOWER()==LOWER() silently returned [].
            base_query += " AND LOWER(direction) LIKE LOWER(@direction) || '%'"
            query_params.append(bigquery.ScalarQueryParameter("direction", "STRING", direction))

        if ticker:
            base_query += " AND ticker = @ticker"
            query_params.append(bigquery.ScalarQueryParameter("ticker", "STRING", ticker))

        base_query += " ORDER BY overnight_score DESC LIMIT @limit"
        query_params.append(bigquery.ScalarQueryParameter("limit", "INTEGER", limit))

        job_config = bigquery.QueryJobConfig(query_parameters=query_params)
        query_job = client.query(base_query, job_config=job_config)

        results = []
        for row in query_job.result():
            results.append(dict(row))

        # Convert date/datetime objects to strings
        for r in results:
            for k, v in r.items():
                if hasattr(v, "isoformat"):
                    r[k] = v.isoformat()
                elif hasattr(v, "strftime"):
                    r[k] = str(v)

        return results

    except Exception as e:
        return [{"error": safe_error(e, "get_enriched_signals")}]


def get_signal_detail(ticker: str, scan_date: str | None = None) -> dict[str, Any]:
    """
    Deep dive on a single ticker's enriched signal — full narrative enrichment
    (news summary, thesis, technicals, catalyst) plus the recommended contract
    and point-in-time features. Served from the leakage-safe enriched view.
    """
    if not client:
        return {"error": "BigQuery client not initialized"}

    try:
        # Determine scan_date if not provided
        if not scan_date:
            # First try to find the latest date for this specific ticker
            query = f"""
                SELECT MAX(scan_date) as max_date
                FROM {_SAFE_ENRICHED}
                WHERE ticker = @ticker
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[bigquery.ScalarQueryParameter("ticker", "STRING", ticker)]
            )
            query_job = client.query(query, job_config=job_config)
            results = query_job.result()
            for row in results:
                scan_date = str(row.max_date) if row.max_date else None
                break

        if not scan_date:
            return {"error": f"No signal found for ticker {ticker}"}

        # Build query
        query = f"""
            SELECT *
            FROM {_SAFE_ENRICHED}
            WHERE ticker = @ticker AND scan_date = @scan_date
            LIMIT 1
        """

        query_params = [
            bigquery.ScalarQueryParameter("ticker", "STRING", ticker),
            bigquery.ScalarQueryParameter("scan_date", "DATE", scan_date),
        ]

        job_config = bigquery.QueryJobConfig(query_parameters=query_params)
        query_job = client.query(query, job_config=job_config)

        results = []
        for row in query_job.result():
            results.append(dict(row))

        if not results:
            return {"error": f"Signal not found for {ticker} on {scan_date}"}

        result = results[0]

        # Convert date/datetime objects to strings
        for k, v in result.items():
            if hasattr(v, "isoformat"):
                result[k] = v.isoformat()
            elif hasattr(v, "strftime"):
                result[k] = str(v)

        return result

    except Exception as e:
        return {"error": safe_error(e, "get_signal_detail")}


def get_freemium_preview(limit: int = 5) -> list[dict[str, Any]]:
    """
    Top N enriched signals for the most recent scan, with minimal fields. Used
    for public/freemium teasers: ticker, direction, score, headline, directional
    UOA dollar volume. No contract specifics or full thesis — use
    get_signal_detail for that.

    Args:
        limit: How many preview rows to return (default 5, max 20).

    Returns:
        List of {ticker, direction, overnight_score, call_dollar_volume,
                 put_dollar_volume, key_headline, scan_date}.
    """
    if not client:
        return [{"error": "BigQuery client not initialized"}]

    limit = clamp(limit, 1, 20, default=5)

    try:
        query = f"""
            WITH latest AS (
                SELECT MAX(scan_date) as d
                FROM {_SAFE_ENRICHED}
            )
            SELECT
                ticker, direction, overnight_score,
                call_dollar_volume, put_dollar_volume,
                key_headline, scan_date
            FROM {_SAFE_ENRICHED}
            WHERE scan_date = (SELECT d FROM latest)
            ORDER BY overnight_score DESC,
                     GREATEST(IFNULL(call_dollar_volume, 0), IFNULL(put_dollar_volume, 0)) DESC
            LIMIT @limit
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("limit", "INTEGER", limit)]
        )
        query_job = client.query(query, job_config=job_config)

        results = []
        for row in query_job.result():
            r = dict(row)
            if r.get("scan_date"):
                r["scan_date"] = str(r["scan_date"])
            results.append(r)

        return results

    except Exception as e:
        return [{"error": safe_error(e, "get_freemium_preview")}]
