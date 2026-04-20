"""
Overnight Edge tools for GammaRips MCP
"""

import logging
from typing import Any

from google.cloud import bigquery, firestore

logger = logging.getLogger(__name__)

# Initialize clients
try:
    client = bigquery.Client(project="profitscout-fida8")
except Exception as e:
    logger.error(f"Failed to initialize BigQuery client: {e}")
    client = None

try:
    fs_client = firestore.Client(project="profitscout-fida8")
except Exception as e:
    logger.error(f"Failed to initialize Firestore client: {e}")
    fs_client = None


def get_overnight_signals(
    scan_date: str | None = None,
    direction: str | None = None,
    min_score: int = 0,
    ticker: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """
    Returns raw overnight scanner signals for a given date.
    """
    if not client:
        return [{"error": "BigQuery client not initialized"}]

    try:
        # Determine scan_date if not provided
        if not scan_date:
            query = "SELECT MAX(scan_date) as max_date FROM `profitscout-fida8.profit_scout.overnight_signals`"
            query_job = client.query(query)
            results = query_job.result()
            for row in results:
                scan_date = str(row.max_date) if row.max_date else None
                break

        if not scan_date:
            return [{"error": "No data found in overnight_signals table"}]

        # Build query
        # Mapping fields to expected output
        base_query = """
            SELECT
                ticker,
                direction,
                overnight_score as score,
                day_volume as volume,
                total_options_dollar_volume as premium,
                recommended_expiration as expiration,
                recommended_strike as strike,
                scan_date
            FROM `profitscout-fida8.profit_scout.overnight_signals`
            WHERE scan_date = @scan_date
        """

        query_params = [bigquery.ScalarQueryParameter("scan_date", "DATE", scan_date)]

        if direction:
            base_query += " AND LOWER(direction) = LOWER(@direction)"
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
        logger.error(f"Error in get_overnight_signals: {e}")
        return [{"error": str(e)}]


def get_enriched_signals(
    scan_date: str | None = None,
    direction: str | None = None,
    ticker: str | None = None,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """
    Returns AI-enriched overnight signals for a scan_date (news, technicals,
    catalyst analysis, contract recommendation).

    Under V5.3, enrichment already gates on `overnight_score >= 1`, spread <= 10%,
    and directional UOA > $500K. This tool returns ALL rows that cleared that gate
    — not a further score filter. The final single tradeable pick is produced by
    signal-notifier (V/OI > 2, 5-15% OTM, VIX <= VIX3M, LIMIT 1) and surfaced via
    `get_todays_pick`.
    """
    if not client:
        return [{"error": "BigQuery client not initialized"}]

    try:
        # Determine scan_date if not provided
        if not scan_date:
            query = "SELECT MAX(scan_date) as max_date FROM `profitscout-fida8.profit_scout.overnight_signals_enriched`"
            query_job = client.query(query)
            results = query_job.result()
            for row in results:
                scan_date = str(row.max_date) if row.max_date else None
                break

        if not scan_date:
            return [{"error": "No data found in overnight_signals_enriched table"}]

        # Build query
        base_query = """
            SELECT *
            FROM `profitscout-fida8.profit_scout.overnight_signals_enriched`
            WHERE scan_date = @scan_date
        """

        query_params = [bigquery.ScalarQueryParameter("scan_date", "DATE", scan_date)]

        if direction:
            base_query += " AND LOWER(direction) = LOWER(@direction)"
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
        logger.error(f"Error in get_enriched_signals: {e}")
        return [{"error": str(e)}]


def get_signal_detail(ticker: str, scan_date: str | None = None) -> dict[str, Any]:
    """
    Deep dive on a single ticker's overnight signal.
    """
    if not client:
        return {"error": "BigQuery client not initialized"}

    try:
        # Determine scan_date if not provided
        if not scan_date:
            # First try to find the latest date for this specific ticker
            query = """
                SELECT MAX(scan_date) as max_date
                FROM `profitscout-fida8.profit_scout.overnight_signals_enriched`
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
        query = """
            SELECT *
            FROM `profitscout-fida8.profit_scout.overnight_signals_enriched`
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
        logger.error(f"Error in get_signal_detail: {e}")
        return {"error": str(e)}


def get_todays_pick(scan_date: str | None = None) -> dict[str, Any]:
    """
    Returns GammaRips' canonical daily V5.3 pick from Firestore todays_pick/{scan_date}.

    This is the single source of truth for "what did GammaRips pick today" —
    written atomically by signal-notifier at ~09:00 ET. The same ticker appears
    on the webapp banner, in the operator email, and (once Phase 2 ships) in the
    WhatsApp push to paid subscribers. Do NOT re-filter the result — the doc IS
    the answer.

    Args:
        scan_date: Filter by date (YYYY-MM-DD). Defaults to most recent.

    Returns:
        {has_pick: bool, ticker?, direction?, recommended_contract?, recommended_strike?,
         recommended_expiration?, recommended_mid_price?, recommended_dte?,
         overnight_score?, vol_oi_ratio?, moneyness_pct?, call_dollar_volume?,
         put_dollar_volume?, vix3m_at_enrich?, vix_now_at_decision?,
         decided_at, effective_at, scan_date, policy_version, skip_reason?}

        When has_pick=false, skip_reason explains why: "no_candidates_passed_gates",
        "regime_fail_closed", or "vix_backwardation".
    """
    if not fs_client:
        return {"error": "Firestore client not initialized"}

    try:
        col = fs_client.collection("todays_pick")
        if scan_date:
            snap = col.document(scan_date).get()
            if not snap.exists:
                return {"error": f"No todays_pick doc for {scan_date}"}
            data = snap.to_dict()
        else:
            # Most recent doc by scan_date DESC.
            q = col.order_by("scan_date", direction=firestore.Query.DESCENDING).limit(1)
            docs = list(q.stream())
            if not docs:
                return {"error": "No todays_pick docs found"}
            data = docs[0].to_dict()

        # Normalize Firestore Timestamp -> ISO8601 for JSON serialization.
        for k, v in list(data.items()):
            if hasattr(v, "isoformat"):
                data[k] = v.isoformat()

        return data

    except Exception as e:
        logger.error(f"Error in get_todays_pick: {e}")
        return {"error": str(e)}


def get_freemium_preview(limit: int = 5) -> list[dict[str, Any]]:
    """
    Top N enriched signals for the most recent scan, with minimal fields. Used
    for public/freemium teasers: ticker, direction, score, headline, directional
    UOA dollar volume. No contract specifics or full thesis — chat agents should
    use get_signal_detail for that.

    Args:
        limit: How many preview rows to return (default 5, max 20).

    Returns:
        List of {ticker, direction, overnight_score, call_dollar_volume,
                 put_dollar_volume, key_headline, scan_date}.
    """
    if not client:
        return [{"error": "BigQuery client not initialized"}]

    limit = max(1, min(int(limit), 20))

    try:
        query = """
            WITH latest AS (
                SELECT MAX(scan_date) as d
                FROM `profitscout-fida8.profit_scout.overnight_signals_enriched`
            )
            SELECT
                ticker, direction, overnight_score,
                call_dollar_volume, put_dollar_volume,
                key_headline, scan_date
            FROM `profitscout-fida8.profit_scout.overnight_signals_enriched`
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
        logger.error(f"Error in get_freemium_preview: {e}")
        return [{"error": str(e)}]
