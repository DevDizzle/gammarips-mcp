"""
Entry-day market snapshot for option contracts (RM-001a + Priority-1A/1B/1D).

Closes the "is this contract liquid RIGHT NOW?" gap: the pool's
`recommended_oi` / `recommended_volume` are session-frozen scan-time
snapshots (the overnight sweep only becomes open interest the next morning),
so an agent needs a fresh read at decision time. Serves OI / session volume /
last trade / day range / underlying price with provenance timestamps.

Two layers (they compose):
  * CACHE-FIRST (Priority-1A): the engine re-fetches liquidity for the WHOLE
    current pool every ~10 minutes during regular trading hours (plus one
    pre-open pass) into `pool_liquidity_snapshot`. `get_contract_snapshot`
    serves that cache when fresh, and `get_pool_liquidity` returns the whole
    pool / a shortlist in ONE metered call.
  * ON-DEMAND LIVE (Priority-1B): `get_contract_snapshot(..., live=True)`
    forces a fresh upstream fetch — for a fresher-than-interval read or for
    a contract NOT in today's pool. Also the automatic fallback when the
    cache has no fresh row.

Deliberately NO quote fields (bid/ask/mid/spread): the current data plan
carries no options quotes — a missing field is honest, a NULL field reads
like a bug. Quote fields are RM-001b, gated on a separate data-purchase
decision; if/when purchased they appear here automatically (the cache table
carries placeholder columns that are omitted while NULL).

LEAKAGE NOTE: everything here is entry-day-LIVE telemetry keyed by explicit
`as_of` provenance — a decision-time freshness read, never a backtest feature.
It is not joined into any as-of <= scan_date feature surface.
"""

import logging
import os
import re
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import requests
from google.cloud import bigquery

from utils.data import BQ as _bq
from utils.data import POOL_LIQUIDITY_TABLE as _POOL_LIQ_TABLE
from utils.safety import GlobalToolBucket, safe_error

logger = logging.getLogger(__name__)

# Process-wide throttle (FIX-1, review 2026-07-06): upstream fetches spend the
# SAME POLYGON_API_KEY the production trading pipeline mounts — an abuse wave
# against a public tool must never get the shared key vendor-throttled and
# degrade the live 10:00 ET entry fetch. Mirrors web_search's pattern and
# holds regardless of transport (the per-IP middleware only sees /rpc).
# Cache reads do NOT consume from this bucket — that is the point of the
# cache: shortlist refreshes stop competing with the production key.
_SNAPSHOT_BUCKET = GlobalToolBucket(per_min=float(os.getenv("RATE_LIMIT_SNAPSHOT_PER_MIN", "30")))

_ET = ZoneInfo("America/New_York")
# OCC-style options ticker as served in the pool's `recommended_contract`,
# e.g. O:UNIT260717C00030000. Charset is strict — this string is placed into
# a URL path / BQ parameter, so nothing outside it may pass.
_CONTRACT_RE = re.compile(r"O:([A-Z]{1,6})([0-9]{6})([CP])([0-9]{8})")
_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_UPSTREAM_BASE = "https://api.polygon.io"

# A cache row older than this (seconds) no longer counts as "fresh" for the
# cache-first path — 900s = 1.5x the engine's ~10-min refresh cadence.
_CACHE_FRESH_S = int(os.getenv("SNAPSHOT_CACHE_FRESH_S", "900"))
_BATCH_MAX_CONTRACTS = 60

_REFRESH_CADENCE_NOTE = (
    "Cache rows are refreshed for the whole current pool every ~10 minutes "
    "during regular trading hours (09:30-16:00 ET) plus one pre-open pass; "
    "open_interest itself updates upstream once each morning. No bid/ask/"
    "spread on this data plan (fields appear only if a quote feed is added); "
    "last_trade is served only when upstream provides it (often absent on "
    "this plan) — day.close is the reliable delayed session mark, "
    "day.last_updated its timestamp."
)


def _truthy(v) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes")


def _ns_to_et_iso(ns: int | None) -> str | None:
    if not ns:
        return None
    try:
        return datetime.fromtimestamp(ns / 1e9, tz=UTC).astimezone(_ET).isoformat()
    except Exception:  # noqa: BLE001
        return None


def _ts_to_et_iso(ts) -> str | None:
    """BQ TIMESTAMP (tz-aware datetime) -> ISO8601 ET."""
    if ts is None:
        return None
    try:
        return ts.astimezone(_ET).isoformat()
    except Exception:  # noqa: BLE001
        return None


def _prune(d: dict[str, Any]) -> dict[str, Any]:
    """Drop None-valued keys — a missing field is honest, a NULL reads like a
    data bug (the RM-001a rule, applied to quote placeholders especially)."""
    return {k: v for k, v in d.items() if v is not None}


def _cache_row_payload(row) -> dict[str, Any]:
    """One pool_liquidity_snapshot BQ row -> the snapshot response shape
    (same shape as the live upstream path, so callers never branch)."""
    greeks = _prune(
        {
            "delta": row["delta"],
            "gamma": row["gamma"],
            "theta": row["theta"],
            "vega": row["vega"],
        }
    )
    day = _prune(
        {
            "open": row["day_open"],
            "high": row["day_high"],
            "low": row["day_low"],
            "close": row["day_close"],
            "last_updated": _ts_to_et_iso(row["day_last_updated"]),
        }
    )
    last_trade = _prune(
        {
            "price": row["last_trade_price"],
            "timestamp": _ts_to_et_iso(row["last_trade_ts"]),
        }
    )
    out = {
        "contract": row["contract"],
        "underlying": row["underlying"],
        "underlying_price": row["underlying_price"],
        "underlying_price_source": row["underlying_price_source"],
        "as_of": _ts_to_et_iso(row["as_of"]),
        "is_preopen": row["is_preopen"],
        "open_interest": row["open_interest"],
        "day_volume": row["day_volume"],
        "day": day or None,
        "last_trade": last_trade or None,
        "implied_volatility": row["implied_volatility"],
        "greeks": greeks or None,
        # RM-001b: quote fields appear ONLY when a quote feed populates them.
        "bid": row["bid"],
        "ask": row["ask"],
        "mid": row["mid"],
        "spread_pct": row["spread_pct"],
        "source": row["source"],
        "is_delayed": row["is_delayed"],
    }
    return _prune(out)


def _read_cache(symbol: str):
    """Latest ok cache row for one contract (bounded to the last 3 days so the
    scan stays cheap as the table grows). Returns the BQ Row or None."""
    if _bq is None:
        return None
    q = f"""
    SELECT * FROM {_POOL_LIQ_TABLE}
    WHERE contract = @contract AND fetch_status = 'ok'
      AND DATE(as_of) >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
    ORDER BY as_of DESC
    LIMIT 1
    """
    try:
        job = _bq.query(
            q,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[bigquery.ScalarQueryParameter("contract", "STRING", symbol)]
            ),
        )
        for row in job.result():
            return row
    except Exception as e:  # noqa: BLE001
        logger.warning(f"market_snapshot cache read failed for {symbol}: {e}")
    return None


def _cache_age_seconds(row) -> int | None:
    try:
        return int((datetime.now(tz=UTC) - row["as_of"]).total_seconds())
    except Exception:  # noqa: BLE001
        return None


def _fetch_underlying_price_upstream(
    underlying: str, api_key: str
) -> tuple[float | None, str | None]:
    """TF-18 fallback when the option snapshot carries no underlying price:
    today's developing daily agg close (delayed) -> previous close. Honest
    provenance in the second slot."""
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        today = datetime.now(tz=_ET).date().isoformat()
        resp = requests.get(
            f"{_UPSTREAM_BASE}/v2/aggs/ticker/{underlying}/range/1/day/{today}/{today}",
            headers=headers,
            timeout=10,
        )
        if resp.status_code == 200:
            results = (resp.json() or {}).get("results") or []
            if results and results[0].get("c"):
                return float(results[0]["c"]), "day_agg_delayed"
    except Exception:  # noqa: BLE001
        pass
    try:
        resp = requests.get(
            f"{_UPSTREAM_BASE}/v2/aggs/ticker/{underlying}/prev",
            headers=headers,
            timeout=10,
        )
        if resp.status_code == 200:
            results = (resp.json() or {}).get("results") or []
            if results and results[0].get("c"):
                return float(results[0]["c"]), "prev_close"
    except Exception:  # noqa: BLE001
        pass
    return None, None


def _fetch_upstream_live(symbol: str, underlying: str) -> dict[str, Any]:
    """Force-fresh upstream option snapshot (the original RM-001a path,
    plus the TF-18 underlying-price fallback). Bucket must be consumed by the
    caller BEFORE calling this."""
    # .strip() is load-bearing: the mounted secret can carry a trailing
    # newline, which is both an invalid header value and (2026-07-06 incident)
    # caused the raw key to echo through the header-validation error.
    api_key = (os.getenv("POLYGON_API_KEY") or "").strip()
    if not api_key:
        return {"error": "market-data credential not configured on the server"}

    # Key travels as a bearer header, never in the URL — requests
    # exceptions embed the full URL, so a query-param key could leak
    # through error strings.
    resp = requests.get(
        f"{_UPSTREAM_BASE}/v3/snapshot/options/{underlying}/{symbol}",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=10,
    )
    if resp.status_code == 404:
        return {
            "error": (
                f"{symbol} not found upstream — expired contracts drop out "
                "of the snapshot feed; check the expiration date"
            )
        }
    resp.raise_for_status()
    res = (resp.json() or {}).get("results") or {}

    day = res.get("day") or {}
    last_trade = res.get("last_trade") or {}
    greeks = res.get("greeks") or {}
    greeks_out = {
        k: greeks.get(k) for k in ("delta", "gamma", "theta", "vega") if greeks.get(k) is not None
    }

    underlying_price = (res.get("underlying_asset") or {}).get("price")
    underlying_price_source = "option_snapshot" if underlying_price else None
    if not underlying_price:
        underlying_price, underlying_price_source = _fetch_underlying_price_upstream(
            underlying, api_key
        )

    return _prune(
        {
            "contract": symbol,
            "underlying": underlying,
            "underlying_price": underlying_price,
            "underlying_price_source": underlying_price_source,
            "as_of": datetime.now(tz=_ET).isoformat(timespec="seconds"),
            "open_interest": res.get("open_interest"),
            "day_volume": day.get("volume"),
            "day": _prune(
                {
                    "open": day.get("open"),
                    "high": day.get("high"),
                    "low": day.get("low"),
                    "close": day.get("close"),
                    "last_updated": _ns_to_et_iso(day.get("last_updated")),
                }
            )
            or None,
            "last_trade": _prune(
                {
                    "price": last_trade.get("price"),
                    "timestamp": _ns_to_et_iso(last_trade.get("sip_timestamp")),
                }
            )
            or None,
            "implied_volatility": res.get("implied_volatility"),
            "greeks": greeks_out or None,
            "source": "upstream option snapshot (per-plan delay applies)",
        }
    )


def get_contract_snapshot(contract: str, live: bool = False) -> dict[str, Any]:
    """
    FRESH (entry-day) snapshot for ONE option contract: open interest, session
    volume, last trade, day range, and the underlying price — the liquidity/
    freshness read the pool rows cannot give you (their `recommended_oi`/
    `recommended_volume` are frozen at scan time; the overnight sweep only
    becomes OI the next morning). Use it at decision time.

    CACHE-FIRST: contracts in the current pool are re-read every ~10 minutes
    during market hours, so the default call is fast and served from that
    cache when a fresh row (<15 min) exists. Pass live=true to force a fresh
    upstream fetch — for a fresher-than-interval read or a contract NOT in
    today's pool (any valid OCC ticker works). To refresh a whole shortlist
    in one call, use `get_pool_liquidity` instead.

    Deliberately serves NO bid/ask/spread (not available on the current data
    plan — absent, not NULL). Assess fill risk from: open_interest (updates
    once each morning), day_volume (live session), last_trade recency, and
    the day range. `retrieved_from` + `as_of` tell you exactly what you got.

    Args:
        contract: OCC-style option ticker exactly as served by the pool tools
            (the `recommended_contract` field), e.g. "O:UNIT260717C00030000".
        live: force a fresh upstream fetch instead of the ~10-min pool cache
            (default false = cache-first with automatic live fallback).

    Returns:
        {contract, underlying, underlying_price, underlying_price_source,
         as_of, open_interest, day_volume, day: {open, high, low, close,
         last_updated}, last_trade: {price, timestamp}, implied_volatility,
         greeks, source, retrieved_from, freshness_note} — plus
         cache_age_seconds on cache hits. Quote fields (bid/ask/mid/
         spread_pct) appear ONLY if a quote feed is ever added.
    """
    m = _CONTRACT_RE.fullmatch((contract or "").strip().upper())
    if not m:
        return {
            "error": (
                "contract must be an OCC-style option ticker like "
                "'O:TICKER260717C00030000' — pass the pool's "
                "recommended_contract field verbatim"
            )
        }
    symbol = m.group(0)
    underlying = m.group(1)
    force_live = _truthy(live)

    cached = None
    if not force_live:
        cached = _read_cache(symbol)
        if cached is not None:
            age = _cache_age_seconds(cached)
            if age is not None and age <= _CACHE_FRESH_S:
                payload = _cache_row_payload(cached)
                payload["retrieved_from"] = "pool_liquidity_cache"
                payload["cache_age_seconds"] = age
                payload["freshness_note"] = (
                    "Served from the engine's interval pool-liquidity cache; "
                    "as_of is the engine's fetch time (ET). "
                    + _REFRESH_CADENCE_NOTE
                    + " Pass live=true for a force-fresh upstream read."
                )
                return payload

    # Live upstream path (forced, cache miss, or stale cache).
    if not _SNAPSHOT_BUCKET.try_consume():
        # A stale cache row with explicit provenance beats a hard error.
        if cached is not None:
            payload = _cache_row_payload(cached)
            payload["retrieved_from"] = "pool_liquidity_cache_stale"
            payload["cache_age_seconds"] = _cache_age_seconds(cached)
            payload["freshness_note"] = (
                "Upstream rate limit hit — serving the most recent cached row "
                "instead. Judge staleness from as_of. " + _REFRESH_CADENCE_NOTE
            )
            return payload
        return {"error": "get_contract_snapshot rate limit exceeded — try again shortly"}

    try:
        payload = _fetch_upstream_live(symbol, underlying)
        if "error" in payload:
            return payload
        payload["retrieved_from"] = "upstream_live"
        payload["freshness_note"] = (
            "Force-fresh upstream read; as_of is the server request time (ET); "
            "judge staleness from day.last_updated. open_interest updates once "
            "daily in the morning; day_volume is the live (delayed) session; "
            "day.close is the reliable session mark — last_trade appears only "
            "when upstream provides it. No bid/ask/spread on this data plan."
        )
        return payload
    except Exception as e:
        if cached is not None:
            payload = _cache_row_payload(cached)
            payload["retrieved_from"] = "pool_liquidity_cache_stale"
            payload["cache_age_seconds"] = _cache_age_seconds(cached)
            payload["freshness_note"] = (
                "Upstream fetch failed — serving the most recent cached row "
                "instead. Judge staleness from as_of. " + _REFRESH_CADENCE_NOTE
            )
            return payload
        return {"error": safe_error(e, "get_contract_snapshot")}


def get_pool_liquidity(
    scan_date: str | None = None, contracts: list[str] | None = None
) -> dict[str, Any]:
    """
    Latest liquidity snapshot for the WHOLE current pool (or your shortlist)
    in ONE call — the batch companion to `get_contract_snapshot`. The engine
    re-reads every pool contract's open interest, session volume, last trade,
    day range, and underlying price every ~10 minutes during market hours
    (plus one pre-open pass); this returns the most recent read per contract,
    each with explicit `as_of` provenance. Built for the ~10:00 ET decision
    window: one call replaces N per-contract fetches at the busiest minute.

    No bid/ask/spread on the current data plan (fields appear only if a quote
    feed is added — absent, not NULL). Judge fill risk from open_interest
    (updates once each morning), day_volume (live session), last_trade
    recency, and the day range. For a single contract outside the pool, or a
    fresher-than-interval read, use `get_contract_snapshot(..., live=true)`.

    Args:
        scan_date: pool date "YYYY-MM-DD" (the scan that produced the pool).
            Default: the most recent pool with snapshots (today's live pool
            during market hours).
        contracts: optional shortlist filter — OCC tickers exactly as served
            in `recommended_contract` (max 60). Default: the whole pool.

    Returns:
        {scan_date, count, freshest_as_of, rows: [snapshot per contract],
         freshness_note} — each row shaped like `get_contract_snapshot`.
    """
    if _bq is None:
        return {"error": "BigQuery client not initialized on the server"}

    params: list[bigquery.ScalarQueryParameter | bigquery.ArrayQueryParameter] = []
    where = ["fetch_status = 'ok'", "DATE(as_of) >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)"]

    if scan_date is not None:
        sd = str(scan_date).strip()
        if not _DATE_RE.fullmatch(sd):
            return {"error": "scan_date must be YYYY-MM-DD"}
        where.append("scan_date = @scan_date")
        params.append(bigquery.ScalarQueryParameter("scan_date", "DATE", sd))

    if contracts is not None:
        if not isinstance(contracts, list) or not contracts:
            return {"error": "contracts must be a non-empty list of OCC option tickers"}
        if len(contracts) > _BATCH_MAX_CONTRACTS:
            return {"error": f"contracts list capped at {_BATCH_MAX_CONTRACTS}"}
        cleaned = []
        for c in contracts:
            m = _CONTRACT_RE.fullmatch(str(c or "").strip().upper())
            if not m:
                return {
                    "error": (
                        f"invalid contract {c!r} — every entry must be an "
                        "OCC-style option ticker like 'O:TICKER260717C00030000' "
                        "(pass recommended_contract verbatim)"
                    )
                }
            cleaned.append(m.group(0))
        where.append("contract IN UNNEST(@contracts)")
        params.append(bigquery.ArrayQueryParameter("contracts", "STRING", sorted(set(cleaned))))

    q = f"""
    WITH latest AS (
      SELECT *, ROW_NUMBER() OVER (PARTITION BY contract ORDER BY as_of DESC) AS rn
      FROM {_POOL_LIQ_TABLE}
      WHERE {" AND ".join(where)}
        AND scan_date = (
          SELECT MAX(scan_date) FROM {_POOL_LIQ_TABLE}
          WHERE {" AND ".join(where)}
        )
    )
    SELECT * EXCEPT(rn) FROM latest WHERE rn = 1
    ORDER BY contract
    """
    try:
        rows = list(
            _bq.query(q, job_config=bigquery.QueryJobConfig(query_parameters=params)).result()
        )
        if not rows:
            return {
                "scan_date": scan_date,
                "count": 0,
                "rows": [],
                "note": (
                    "No liquidity snapshots found — the interval refresh runs "
                    "only on NYSE trading days ~09:20-16:00 ET, and only for "
                    "pool contracts. For an arbitrary contract use "
                    "get_contract_snapshot(..., live=true)."
                ),
            }
        payloads = [_cache_row_payload(r) for r in rows]
        freshest = max(r["as_of"] for r in rows)
        return {
            "scan_date": str(rows[0]["scan_date"]),
            "count": len(payloads),
            "freshest_as_of": _ts_to_et_iso(freshest),
            "rows": payloads,
            "freshness_note": (
                "One row per contract, most recent read first-per-contract; "
                "judge staleness from each row's as_of (ET). " + _REFRESH_CADENCE_NOTE
            ),
        }
    except Exception as e:
        return {"error": safe_error(e, "get_pool_liquidity")}
