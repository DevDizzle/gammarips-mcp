"""
Entry-day market snapshot for a single option contract (RM-001a).

Closes the "is this contract liquid RIGHT NOW?" gap: the pool's
`recommended_oi` / `recommended_volume` are session-frozen scan-time
snapshots (the overnight sweep only becomes open interest the next morning),
so an agent needs a fresh read at decision time. Serves OI / session volume /
last trade / day range with provenance timestamps.

Deliberately NO quote fields (bid/ask/mid/spread): the current data plan
carries no options quotes — a missing field is honest, a NULL field reads
like a bug. Quote fields are RM-001b, gated on a separate data-purchase
decision.
"""

import logging
import os
import re
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import requests

from utils.safety import GlobalToolBucket, safe_error

logger = logging.getLogger(__name__)

# Process-wide throttle (FIX-1, review 2026-07-06): this tool spends the SAME
# POLYGON_API_KEY the production trading pipeline mounts — an abuse wave
# against a public tool must never get the shared key vendor-throttled and
# degrade the live 10:00 ET entry fetch. Mirrors web_search's pattern and
# holds regardless of transport (the per-IP middleware only sees /rpc).
_SNAPSHOT_BUCKET = GlobalToolBucket(per_min=float(os.getenv("RATE_LIMIT_SNAPSHOT_PER_MIN", "30")))

_ET = ZoneInfo("America/New_York")
# OCC-style options ticker as served in the pool's `recommended_contract`,
# e.g. O:UNIT260717C00030000. Charset is strict — this string is placed into
# a URL path, so nothing outside it may pass.
_CONTRACT_RE = re.compile(r"O:([A-Z]{1,6})([0-9]{6})([CP])([0-9]{8})")
_UPSTREAM_BASE = "https://api.polygon.io"


def _ns_to_et_iso(ns: int | None) -> str | None:
    if not ns:
        return None
    try:
        return datetime.fromtimestamp(ns / 1e9, tz=UTC).astimezone(_ET).isoformat()
    except Exception:  # noqa: BLE001
        return None


def get_contract_snapshot(contract: str) -> dict[str, Any]:
    """
    FRESH (entry-day) snapshot for ONE option contract: open interest, session
    volume, last trade, and day range — the liquidity/freshness read the pool
    rows cannot give you (their `recommended_oi`/`recommended_volume` are
    frozen at scan time; the overnight sweep only becomes OI the next
    morning). Use it at decision time on your shortlist, one contract per
    call.

    Deliberately serves NO bid/ask/spread (not available on the current data
    plan — absent, not NULL). Assess fill risk from: open_interest (updates
    once each morning), day_volume (live session), last_trade recency, and
    the day range.

    Args:
        contract: OCC-style option ticker exactly as served by the pool tools
            (the `recommended_contract` field), e.g. "O:UNIT260717C00030000".

    Returns:
        {contract, underlying, underlying_price, as_of, open_interest,
         day_volume, day: {open, high, low, close, last_updated},
         last_trade: {price, timestamp}, implied_volatility, greeks,
         source, freshness_note}
    """
    # .strip() is load-bearing: the mounted secret can carry a trailing
    # newline, which is both an invalid header value and (2026-07-06 incident)
    # caused the raw key to echo through the header-validation error.
    api_key = (os.getenv("POLYGON_API_KEY") or "").strip()
    if not api_key:
        return {"error": "market-data credential not configured on the server"}

    if not _SNAPSHOT_BUCKET.try_consume():
        return {"error": "get_contract_snapshot rate limit exceeded — try again shortly"}

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

    try:
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
            k: greeks.get(k)
            for k in ("delta", "gamma", "theta", "vega")
            if greeks.get(k) is not None
        }

        return {
            "contract": symbol,
            "underlying": underlying,
            "underlying_price": (res.get("underlying_asset") or {}).get("price"),
            "as_of": datetime.now(tz=_ET).isoformat(timespec="seconds"),
            "open_interest": res.get("open_interest"),
            "day_volume": day.get("volume"),
            "day": {
                "open": day.get("open"),
                "high": day.get("high"),
                "low": day.get("low"),
                "close": day.get("close"),
                "last_updated": _ns_to_et_iso(day.get("last_updated")),
            },
            "last_trade": {
                "price": last_trade.get("price"),
                "timestamp": _ns_to_et_iso(last_trade.get("sip_timestamp")),
            },
            "implied_volatility": res.get("implied_volatility"),
            "greeks": greeks_out or None,
            "source": "upstream option snapshot (per-plan delay applies)",
            "freshness_note": (
                "as_of is the server request time (ET); judge staleness from "
                "day.last_updated and last_trade.timestamp. open_interest "
                "updates once daily in the morning; day_volume is the live "
                "session. No bid/ask/spread on this data plan."
            ),
        }

    except Exception as e:
        return {"error": safe_error(e, "get_contract_snapshot")}
