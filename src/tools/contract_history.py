"""
Contract mark series + intraday replay (RM-004 data / RM-002).

These tools serve the RAW PRICE DATA a user's OWN entry/exit rule needs —
daily marks to poll a live paper position and replay a closed one
(`get_contract_marks`).

PRODUCT BOUNDARY (owner-set): the simulator/rule engine lives with the USER
(the harness), never here. These tools do not simulate, score, or judge an
exit — they return bars. `estimate_exit_rule` (research color, cohort-level)
is the only distributional companion, and it carries its own research-only
framing.

Data: upstream option aggregates (the same feed the engine's own labeler
replays from). All bars are historical/delayed market data with explicit
timestamps — leakage-safe by construction (nothing here is a feature; it is
the tape).
"""

import logging
import os
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import requests

from utils.safety import GlobalToolBucket, safe_error

logger = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")
_CONTRACT_RE = re.compile(r"O:([A-Z]{1,6})([0-9]{6})([CP])([0-9]{8})")
_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_UPSTREAM_BASE = "https://api.polygon.io"

# Shared production key — same throttle posture as the snapshot tools.
_HISTORY_BUCKET = GlobalToolBucket(per_min=float(os.getenv("RATE_LIMIT_HISTORY_PER_MIN", "30")))

# Daily-mark range cap. Pool contracts live ~7-45 DTE; 120 days covers any
# realistic position window with buffer while bounding the payload.
_MAX_SPAN_DAYS = int(os.getenv("CONTRACT_MARKS_MAX_SPAN_DAYS", "120"))

_BOUNDARY_NOTE = (
    "Raw marks only — apply YOUR OWN entry/exit rule to them; this server "
    "does not simulate or validate exits. Paper-trade research data; not "
    "investment advice."
)


def _fetch_aggs(
    symbol: str, timespan: str, start: str, end: str, api_key: str
) -> list[dict] | dict:
    """Upstream aggregates fetch -> results list, or {error}. Key travels as a
    bearer header, never in the URL."""
    try:
        resp = requests.get(
            f"{_UPSTREAM_BASE}/v2/aggs/ticker/{symbol}/range/1/{timespan}/{start}/{end}",
            params={"adjusted": "true", "sort": "asc", "limit": 50000},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15,
        )
        if resp.status_code == 404:
            return {"error": f"{symbol} not found upstream — check the contract ticker"}
        resp.raise_for_status()
        body = resp.json() or {}
        results = body.get("results")
        return results if isinstance(results, list) else []
    except Exception as e:  # noqa: BLE001
        return {"error": safe_error(e, "contract_history")}


def _validate_contract(contract: str) -> str | None:
    m = _CONTRACT_RE.fullmatch(str(contract or "").strip().upper())
    return m.group(0) if m else None


def get_contract_marks(
    contract: str, from_date: str | None = None, to_date: str | None = None
) -> dict[str, Any]:
    """
    DAILY mark series (OHLCV) for one option contract over a date range — the
    data you need to mark a live paper position day by day, or to replay a
    closed one under YOUR OWN exit rule. Composes with `get_contract_snapshot`
    (the right-now read).

    Marks are option-premium daily bars from the upstream aggregates feed
    (delayed per plan; thin contracts can have gap days with no bar — a
    missing date means NO trades printed that day, not a data bug). The
    close is the honest end-of-day mark on this quotes-less data plan.

    This server does NOT simulate exits — bring your own rule (the RM-004
    boundary). For distributional exit research use `estimate_exit_rule` /
    `get_harvest_curve`; for excursion context use `get_opportunity_surface`.

    Args:
        contract: OCC-style option ticker exactly as served by the pool tools
            (e.g. "O:UNIT260717C00030000").
        from_date: start "YYYY-MM-DD" (default: 30 days before to_date).
        to_date: end "YYYY-MM-DD" inclusive (default: today ET). Span is
            capped at 120 days.

    Returns:
        {contract, from_date, to_date, bar_count, bars: [{date, open, high,
         low, close, volume, vwap, transactions}], source, note}
    """
    symbol = _validate_contract(contract)
    if not symbol:
        return {
            "error": (
                "contract must be an OCC-style option ticker like "
                "'O:TICKER260717C00030000' — pass the pool's "
                "recommended_contract field verbatim"
            )
        }

    today_et = datetime.now(_ET).date()
    end_s = str(to_date).strip() if to_date is not None else today_et.isoformat()
    # strptime, not just the shape regex — '2026-02-30' must return the
    # structured error, not raise out of the tool (review F2)
    try:
        end_d = datetime.strptime(end_s, "%Y-%m-%d").date()
    except ValueError:
        return {"error": "to_date must be a real YYYY-MM-DD date"}
    if from_date is not None:
        start_s = str(from_date).strip()
        try:
            start_d = datetime.strptime(start_s, "%Y-%m-%d").date()
        except ValueError:
            return {"error": "from_date must be a real YYYY-MM-DD date"}
    else:
        start_d = end_d - timedelta(days=30)
        start_s = start_d.isoformat()
    if start_s > end_s:
        return {"error": "from_date must be on or before to_date"}
    span = (end_d - start_d).days
    if span > _MAX_SPAN_DAYS:
        return {"error": f"date span capped at {_MAX_SPAN_DAYS} days (asked for {span})"}

    api_key = (os.getenv("POLYGON_API_KEY") or "").strip()
    if not api_key:
        return {"error": "market-data credential not configured on the server"}
    if not _HISTORY_BUCKET.try_consume():
        return {"error": "get_contract_marks rate limit exceeded — try again shortly"}

    results = _fetch_aggs(symbol, "day", start_s, end_s, api_key)
    if isinstance(results, dict):
        return results

    bars = []
    for r in results:
        ts = r.get("t")
        try:
            d = datetime.fromtimestamp(int(ts) / 1e3, tz=UTC).astimezone(_ET).date().isoformat()
        except (TypeError, ValueError, OSError, OverflowError):
            continue
        bars.append(
            {
                "date": d,
                "open": r.get("o"),
                "high": r.get("h"),
                "low": r.get("l"),
                "close": r.get("c"),
                "volume": r.get("v"),
                "vwap": r.get("vw"),
                "transactions": r.get("n"),
            }
        )

    return {
        "contract": symbol,
        "from_date": start_s,
        "to_date": end_s,
        "bar_count": len(bars),
        "bars": bars,
        "source": "upstream option daily aggregates (per-plan delay applies)",
        "note": (
            ("No bars in this window — the contract may not have traded, or the "
             "window predates its listing / postdates its expiry. ")
            if not bars
            else ""
        )
        + _BOUNDARY_NOTE,
    }
