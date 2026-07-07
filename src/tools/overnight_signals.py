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
import re
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

# TF-02: the safe view carries long narrative columns (thesis, news_summary,
# flow_intent_reasoning, technicals) — full rows for the whole pool exceed the
# tool-result cap (~160k chars for 50 rows). Default calls project this
# decision-relevant scalar set instead; `fields` gives explicit projection and
# `summary=False` restores full rows.
_SUMMARY_COLUMNS = [
    "scan_date",
    "ticker",
    "direction",
    "overnight_score",
    "key_headline",
    "catalyst_type",
    "recommended_contract",
    "recommended_strike",
    "recommended_expiration",
    "recommended_dte",
    "recommended_delta",
    "recommended_mid_price",
    "recommended_oi",
    "recommended_volume",
    "moneyness_pct",
    "underlying_price",
    "mom_60",
    "risk_reward_ratio",
    "atr_normalized_move",
    "call_dollar_volume",
    "put_dollar_volume",
]

# TF-15: `is_tradeable` is a legacy premium-flag combo from enrichment
# ((hedge AND high_rr) OR (hedge AND high_atr)) whose name reads to an agent
# like a liquidity/tradeability verdict — it is not one (it was false on an
# entire live pool). Dropped from every response; the component flags
# premium_hedge / premium_high_rr / premium_high_atr remain served.
_DROP_FIELDS = {"is_tradeable"}

_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")  # used with fullmatch only
_MAX_FIELDS = 64
_view_columns_cache: list[str] | None = None


def _view_columns() -> list[str] | None:
    """Column names of the safe view (cached). None if lookup fails —
    callers then fall back to regex-only identifier validation and BigQuery
    fails loudly on any unknown column."""
    global _view_columns_cache
    if _view_columns_cache is None and client:
        try:
            table = client.get_table(_SAFE_ENRICHED.strip("`"))
            _view_columns_cache = [f.name for f in table.schema]
        except Exception as e:  # pragma: no cover - network dependent
            logger.warning(f"safe-view schema lookup failed: {e}")
    return _view_columns_cache


def _strip_dropped(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for r in rows:
        for f in _DROP_FIELDS:
            r.pop(f, None)
    return rows


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
    summary: bool = True,
    fields: list[str] | None = None,
    offset: int = 0,
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

    Response size: by default (`summary=True`) rows carry ~21 decision-relevant
    scalar columns, so the full pool fits in one response. Pass `fields=[...]`
    to project exactly the columns you want (STRICT: any unknown/malformed
    name rejects the call and returns the full `valid_fields` catalog), or
    `summary=False` for complete rows including the long narrative fields
    (thesis, news_summary) — combine that with `ticker` or a small `limit`.
    Page with `offset` (rows are ordered by overnight_score DESC, ticker).

    Served from a leakage-safe view: forward-outcome columns are physically
    stripped, so historical dates can be queried without seeing the future.
    Liquidity caveat: `recommended_oi`/`recommended_volume` are scan-time
    snapshots, not live values; `recommended_spread_pct` is permanently NULL.

    Args:
        scan_date: YYYY-MM-DD (default: latest scan).
        direction: "bull"/"bear" prefix filter.
        ticker: exact ticker filter.
        limit: max rows (default 25, clamped 1-50).
        summary: True (default) = compact decision columns; False = full rows.
        fields: explicit column projection (overrides `summary`).
        offset: pagination offset (clamped 0-500).
    """
    if not client:
        return [{"error": "BigQuery client not initialized"}]

    limit = clamp(limit, 1, 50, default=25)
    offset = clamp(offset, 0, 500, default=0)

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

        # Column projection. Identifiers can't be query parameters, so they are
        # regex-validated (identifier charset only) and checked against the
        # view schema; the dropped-field list applies on every path.
        if fields:
            # STRICT projection (TF-16): any malformed, unknown, or removed
            # field rejects the whole call — a typo must never silently become
            # a missing column. Order-preserving dedupe + size cap.
            seen: set[str] = set()
            requested: list[str] = []
            rejected: list[str] = []
            for f in fields:
                if isinstance(f, str) and _IDENT_RE.fullmatch(f) and f not in _DROP_FIELDS:
                    if f not in seen:
                        seen.add(f)
                        requested.append(f)
                else:
                    rejected.append(str(f)[:80])
            requested = requested[:_MAX_FIELDS]
            valid = _view_columns()
            if valid is not None:
                known = set(valid)
                rejected += [f for f in requested if f not in known]
                requested = [f for f in requested if f in known]
            if rejected or not requested:
                err: dict[str, Any] = {
                    "error": (
                        f"Rejected field(s): {sorted(set(rejected)) or list(fields)} — "
                        "no query run (strict: unknown names reject the call so a "
                        "typo can't silently become a missing column)."
                    )
                }
                if valid is not None:
                    err["valid_fields"] = sorted(set(valid) - _DROP_FIELDS)
                return [err]
            select_list = ", ".join(f"`{c}`" for c in requested)
        elif summary:
            select_list = ", ".join(f"`{c}`" for c in _SUMMARY_COLUMNS)
        else:
            # SELECT * is safe here BECAUSE this is the guarded view — the raw
            # table would leak win-tracker forward-outcome columns.
            select_list = "*"

        base_query = f"""
            SELECT {select_list}
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

        # Deterministic ordering (ticker tie-break) so offset paging is stable.
        base_query += " ORDER BY overnight_score DESC, ticker LIMIT @limit OFFSET @offset"
        query_params.append(bigquery.ScalarQueryParameter("limit", "INTEGER", limit))
        query_params.append(bigquery.ScalarQueryParameter("offset", "INTEGER", offset))

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

        return _strip_dropped(results)

    except Exception as e:
        return [{"error": safe_error(e, "get_enriched_signals")}]


def _ticker_pool_dates(ticker: str, limit: int = 10) -> list[str]:
    """Recent scan_dates on which a ticker appears in the enriched pool."""
    q = f"""
        SELECT CAST(scan_date AS STRING) AS d
        FROM {_SAFE_ENRICHED}
        WHERE ticker = @ticker
        ORDER BY scan_date DESC
        LIMIT {int(limit)}
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("ticker", "STRING", ticker)]
    )
    return [r.d for r in client.query(q, job_config=job_config).result()]


_NOT_IN_POOL_NOTE = (
    "The curated pool is ~50 names/day — most tickers on most days are simply "
    "not in it (that's the anti-firehose design; there is no arbitrary-ticker "
    "analysis path). Use get_overnight_signals for the raw pre-curation scan."
)


def get_signal_detail(
    ticker: str, scan_date: str | None = None, full: bool = False
) -> dict[str, Any]:
    """
    Deep dive on a single ticker's enriched signal — thesis, catalyst, the
    recommended contract, and point-in-time features. Served from the
    leakage-safe enriched view.

    By default the extra-long narrative fields (news_summary,
    flow_intent_reasoning) are omitted to keep the response tight — the thesis
    and all decision fields are always included. Pass `full=true` for
    everything. If the ticker is not in the pool for the requested date, the
    error lists the recent dates on which it DOES appear.
    """
    if not client:
        return {"error": "BigQuery client not initialized"}

    try:
        # Determine scan_date if not provided
        if not scan_date:
            dates = _ticker_pool_dates(ticker, limit=10)
            if not dates:
                return {
                    "error": f"{ticker} does not appear in the enriched pool.",
                    "note": _NOT_IN_POOL_NOTE,
                }
            scan_date = dates[0]

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
            dates = _ticker_pool_dates(ticker, limit=10)
            if dates:
                return {
                    "error": f"{ticker} is not in the pool for scan_date {scan_date}.",
                    "ticker_appears_on": dates,
                    "note": _NOT_IN_POOL_NOTE + " Pass one of the listed scan_dates.",
                }
            return {
                "error": f"{ticker} does not appear in the enriched pool.",
                "note": _NOT_IN_POOL_NOTE,
            }

        result = results[0]

        # Convert date/datetime objects to strings
        for k, v in result.items():
            if hasattr(v, "isoformat"):
                result[k] = v.isoformat()
            elif hasattr(v, "strftime"):
                result[k] = str(v)

        for f in _DROP_FIELDS:
            result.pop(f, None)

        # TF-10: trim the extra-long narrative by default; thesis stays.
        if not full:
            omitted = [k for k in ("news_summary", "flow_intent_reasoning") if k in result]
            for k in omitted:
                result.pop(k)
            if omitted:
                result["omitted_fields"] = omitted
                result["omitted_note"] = "Long narrative omitted by default — pass full=true."

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
