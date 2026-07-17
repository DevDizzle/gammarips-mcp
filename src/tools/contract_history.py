"""
Contract mark series + intraday replay (RM-004 data / RM-002).

These tools serve the RAW PRICE DATA a user's OWN entry/exit rule needs —
daily marks to poll a live paper position and replay a closed one
(`get_contract_marks`), and the per-session minute path with exact
first-crossing readout (`replay_contract`, RM-002).

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
from google.cloud import bigquery

from utils.data import BQ as _bq
from utils.data import MINUTE_PATHS_TABLE as _MINUTE_PATHS_TABLE
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


def _ms_to_et_iso(ms) -> str | None:
    try:
        return datetime.fromtimestamp(int(ms) / 1e3, tz=UTC).astimezone(_ET).isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


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
            (
                "No bars in this window — the contract may not have traded, or the "
                "window predates its listing / postdates its expiry. "
            )
            if not bars
            else ""
        )
        + _BOUNDARY_NOTE,
    }


def _read_minute_cache(symbol: str, date_s: str) -> list[dict]:
    """Minute bars for (contract, ET session date) from the engine's
    option_minute_paths table. [] on miss/failure."""
    if _bq is None:
        return []
    q = f"""
    SELECT ts, open, high, low, close, volume, vwap, transactions
    FROM {_MINUTE_PATHS_TABLE}
    WHERE contract = @contract AND bar_date = @d
      -- partition pruning: a bar's entry_day is at most ~8 calendar days
      -- before its bar_date (3-trading-day window incl. long weekends)
      AND entry_day BETWEEN DATE_SUB(@d, INTERVAL 8 DAY) AND @d
    ORDER BY ts
    """
    try:
        rows = _bq.query(
            q,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("contract", "STRING", symbol),
                    bigquery.ScalarQueryParameter("d", "DATE", date_s),
                ]
            ),
        ).result()
        return [
            {
                "t": r.ts.astimezone(_ET).isoformat(),
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "volume": r.volume,
                "vwap": r.vwap,
                "transactions": r.transactions,
            }
            for r in rows
        ]
    except Exception as e:  # noqa: BLE001
        logger.warning(f"replay_contract cache read failed for {symbol} {date_s}: {e}")
        return []


def replay_contract(
    contract: str,
    date: str,
    target_pct: float | None = None,
    stop_pct: float | None = None,
) -> dict[str, Any]:
    """
    INTRADAY minute path for one option contract on one session — the exact
    tape an intraday entry/exit rule replays against (RM-002). Optionally
    pass a bracket (target_pct/stop_pct, PERCENT of the 10:00 ET anchor) and
    the response also reports the exact FIRST-CROSSING sequence: when each
    level was first touched and which came first — measured from the tape,
    not inferred from extremes.

    Pool contracts' excursion windows (entry day + 2 sessions) are served
    from the engine's minute-path table; anything else falls back to an
    upstream minute-aggregates fetch, so ANY contract/session in plan history
    works. Option tape is THIN — minutes with no prints have no bar, and
    lows between prints are unobservable; treat touch times as evidence, not
    tick-perfect truth.

    This server does NOT simulate or validate exits (the first-crossing
    readout is a fact about the past tape, not a recommendation) — the rule
    engine is yours. For cohort-level rule scoring use `estimate_exit_rule`.

    Args:
        contract: OCC-style option ticker (e.g. "O:UNIT260717C00030000").
        date: ET session date "YYYY-MM-DD".
        target_pct: optional +X% level (percent of the anchor mark, e.g. 40).
        stop_pct: optional -Y% level (e.g. 30 or -30 both mean -30%).

    Returns:
        {contract, date, bar_count, bars: [{t, open, high, low, close,
         volume, ...}], anchor: {price, timestamp, definition},
         first_crossing?: {target_level, stop_level, first_target_touch,
         first_stop_touch, first: TARGET|STOP|AMBIGUOUS_SAME_BAR|NONE},
         retrieved_from, note}
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
    date_s = str(date or "").strip()
    try:
        datetime.strptime(date_s, "%Y-%m-%d")
    except ValueError:
        return {"error": "date must be a real YYYY-MM-DD date"}

    bars = _read_minute_cache(symbol, date_s)
    retrieved_from = "minute_path_table"
    if not bars:
        api_key = (os.getenv("POLYGON_API_KEY") or "").strip()
        if not api_key:
            return {"error": "market-data credential not configured on the server"}
        if not _HISTORY_BUCKET.try_consume():
            return {"error": "replay_contract rate limit exceeded — try again shortly"}
        results = _fetch_aggs(symbol, "minute", date_s, date_s, api_key)
        if isinstance(results, dict):
            return results
        retrieved_from = "upstream_live"
        for r in results:
            t_iso = _ms_to_et_iso(r.get("t"))
            if t_iso is None or t_iso[:10] != date_s:
                continue
            bars.append(
                {
                    "t": t_iso,
                    "open": r.get("o"),
                    "high": r.get("h"),
                    "low": r.get("l"),
                    "close": r.get("c"),
                    "volume": r.get("v"),
                    "vwap": r.get("vw"),
                    "transactions": r.get("n"),
                }
            )

    session_complete = date_s < datetime.now(_ET).date().isoformat()
    out: dict[str, Any] = {
        "contract": symbol,
        "date": date_s,
        "bar_count": len(bars),
        "bars": bars,
        "retrieved_from": retrieved_from,
        "session_complete": session_complete,
        "note": (
            (
                "No bars this session — the contract may not have traded that day. "
                if not bars
                else ""
            )
            + (
                ""
                if session_complete
                else "SESSION NOT COMPLETE — this is the partial tape to now "
                "(delayed); any first-crossing verdict is partial, not final. "
            )
            + "Thin-tape caveat: no bar = no prints that minute; lows between "
            "prints are unobservable. " + _BOUNDARY_NOTE
        ),
    }
    if not bars:
        return out

    # 10:00 ET anchor — the pool's entry convention. First bar at/after 10:00;
    # falls back to the session's first bar (flagged) for late-open tapes.
    anchor_bar = next((b for b in bars if b["t"][11:16] >= "10:00"), None)
    anchored_late = anchor_bar is None
    if anchor_bar is None:
        anchor_bar = bars[0]
    anchor_px = anchor_bar.get("close") or anchor_bar.get("open")
    out["anchor"] = {
        "price": anchor_px,
        "timestamp": anchor_bar["t"],
        "definition": (
            "close of the first bar at/after 10:00 ET (pool entry convention; "
            "no slippage applied)"
            + (
                " — NOTE: no 10:00+ bar this session, anchored to the first bar"
                if anchored_late
                else ""
            )
        ),
    }

    if (target_pct is not None or stop_pct is not None) and anchor_px:
        t_lvl = (
            anchor_px * (1 + max(1.0, min(300.0, abs(float(target_pct)))) / 100.0)
            if target_pct is not None
            else None
        )
        s_lvl = (
            anchor_px * (1 - max(1.0, min(95.0, abs(float(stop_pct)))) / 100.0)
            if stop_pct is not None
            else None
        )
        after = [b for b in bars if b["t"] >= anchor_bar["t"]]
        first_t = next(
            (b["t"] for b in after if t_lvl is not None and (b.get("high") or 0) >= t_lvl),
            None,
        )
        first_s = next(
            (
                b["t"]
                for b in after
                if s_lvl is not None and b.get("low") is not None and b["low"] <= s_lvl
            ),
            None,
        )
        if first_t and first_s:
            first = (
                "AMBIGUOUS_SAME_BAR"
                if first_t == first_s
                else ("TARGET" if first_t < first_s else "STOP")
            )
        elif first_t:
            first = "TARGET"
        elif first_s:
            first = "STOP"
        else:
            first = "NONE"
        out["first_crossing"] = {
            "target_level": round(t_lvl, 4) if t_lvl else None,
            "stop_level": round(s_lvl, 4) if s_lvl else None,
            "first_target_touch": first_t,
            "first_stop_touch": first_s,
            "first": first,
            "note": (
                "Bar-level touches off the 10:00 ET anchor. Same-bar touches "
                "are AMBIGUOUS (intrabar order unknowable) — the engine's own "
                "labeler resolves that case STOP-first (pessimistic)."
                + (
                    ""
                    if session_complete
                    else " SESSION NOT COMPLETE — this verdict covers the "
                    "partial tape to now and can still change."
                )
            ),
        }
        out["first_crossing"] = {k: v for k, v in out["first_crossing"].items() if v is not None}

    return out
