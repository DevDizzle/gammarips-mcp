"""
Earnings-window primitive (RM-003 / GAP-003).

Feeds doctrine hard-exclusion #1: never hold a long single-leg option through
an earnings print (IV crush; literature-settled — De Silva 2026 RoF,
Cao/Han 2013 JFE). The engine applies this rail at PICK time, not in the
pool, so pool rows can carry earnings-window names — an agent must check for
itself. This tool answers, in ONE call, "does this candidate report earnings
on/before my contract's expiration?"

Source: FMP (the same provider the engine's own earnings rail uses), dual
path: per-symbol `/stable/earnings` first (precise, includes dates beyond the
calendar horizon), falling back to the range `/stable/earnings-calendar`
(one cached fetch covers every covered ticker for hours). Earnings dates are
public, known-ahead information — leakage-safe by nature.

COVERAGE HONESTY (measured 2026-07-07): this FMP plan tier only covers
major/widely-held names — the per-symbol endpoint 402s on small caps and the
range calendar returned ~81 rows over 90 days (real peak weeks have
hundreds). The tool therefore reports an explicit `coverage` field; an
uncovered ticker returns `earnings_in_window: null` with instructions to
verify externally. (The engine's pick-time rail uses the same range endpoint
and shares this blind spot — flagged to the owner 2026-07-07.)

FAIL-CLOSED SEMANTICS: when the date is unknown or the provider is
unreachable, the response says so explicitly and `earnings_in_window` is null
— per doctrine, treat unknown as IN-window (do not trade through a print you
cannot rule out).
"""

import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import requests

from utils.safety import GlobalToolBucket, safe_error

logger = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")
_TICKER_RE = re.compile(r"[A-Z][A-Z0-9.\-]{0,9}")
_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
# Same OCC shape the snapshot tools accept — lets a caller pass the pool's
# recommended_contract verbatim and get ticker + expiration derived for free.
_CONTRACT_RE = re.compile(r"O:([A-Z]{1,6})([0-9]{6})([CP])([0-9]{8})")

# The FMP key is shared with the production pipeline (the notifier's earnings
# rail + enrichment). Same posture as the Polygon snapshot bucket: a public
# tool must never get the shared key vendor-throttled.
_EARNINGS_BUCKET = GlobalToolBucket(per_min=float(os.getenv("RATE_LIMIT_EARNINGS_PER_MIN", "20")))

# HARD DAILY BUDGET on upstream FMP calls (review F2, 2026-07-07). The bucket
# is a rate, not a budget — FMP plans carry DAILY quotas, and quota exhaustion
# on the shared key is a denial-of-signal attack on the production earnings
# rail (the notifier stands down fail-closed → no pick that day). Legitimate
# load is ~pool-size per 6h cache window, so 150/day is invisible to real
# users. Resets at ET midnight; when spent, callers get the fail-closed error.
_DAILY_BUDGET = int(os.getenv("EARNINGS_DAILY_BUDGET", "150"))
_budget_state = {"day": None, "spent": 0}


def _budget_consume(n: int = 1) -> bool:
    """Consume n upstream-call credits from today's budget. Thread-safe."""
    today = datetime.now(_ET).date().isoformat()
    with _cache_lock:
        if _budget_state["day"] != today:
            _budget_state["day"] = today
            _budget_state["spent"] = 0
        if _budget_state["spent"] + n > _DAILY_BUDGET:
            return False
        _budget_state["spent"] += n
        return True

# Earnings dates move on a quarterly cadence — a short in-process TTL cache
# keeps repeat shortlist checks from spending provider quota.
_CACHE_TTL_S = int(os.getenv("EARNINGS_CACHE_TTL_S", str(6 * 3600)))
_cache: dict[str, tuple[float, dict]] = {}
_cache_lock = threading.Lock()

# Range-calendar fallback horizon. Pool contracts cap at 45 DTE; 90 days
# covers every expiration we serve with buffer.
_CALENDAR_HORIZON_DAYS = int(os.getenv("EARNINGS_CALENDAR_HORIZON_DAYS", "90"))
# One whole-calendar fetch serves every fallback lookup for hours.
_calendar_cache: dict[str, tuple[float, dict[str, list[str]] | None]] = {}

_FAIL_CLOSED_NOTE = (
    "Earnings date UNKNOWN — per the no-options-through-earnings doctrine, "
    "treat this as IN-window (fail closed) unless you can verify the date "
    "another way."
)

_ESTIMATE_NOTE = (
    "Forward earnings dates are provider estimates until the company "
    "confirms — re-check close to the date."
)


def _fetch_next_earnings(ticker: str, api_key: str) -> dict[str, Any]:
    """FMP per-symbol fetch -> {next_earnings_date, last_reported_date,
    coverage} or {error}. 402 (symbol not in this plan tier) triggers the
    range-calendar fallback. Never raises."""
    try:
        # apikey travels as a header, not a query param — URLs end up in error
        # logs verbatim (same discipline as the engine's earnings rail).
        resp = requests.get(
            "https://financialmodelingprep.com/stable/earnings",
            params={"symbol": ticker, "limit": 5},
            headers={"apikey": api_key},
            timeout=15,
        )
        if resp.status_code == 402:
            # symbol outside this plan tier's per-symbol coverage — try the
            # range calendar before declaring it uncovered.
            return _calendar_lookup(ticker, api_key)
        resp.raise_for_status()
        rows = resp.json()
    except Exception as e:  # noqa: BLE001
        return {"error": safe_error(e, "get_earnings_window")}

    # FMP quota-exhausted / auth errors come back as HTTP 200 with a dict
    # body. That must NOT read as "no earnings scheduled" — fail closed.
    if not isinstance(rows, list):
        logger.error(f"FMP non-list payload for {ticker}: {str(rows)[:200]}")
        return {"error": "earnings provider returned an error payload (quota/auth) — unknown, treat as in-window"}

    today = datetime.now(_ET).date().isoformat()
    future = sorted(
        str(r.get("date"))
        for r in rows
        if isinstance(r, dict) and r.get("date") and str(r.get("date")) >= today
    )
    past = sorted(
        str(r.get("date"))
        for r in rows
        if isinstance(r, dict) and r.get("date") and str(r.get("date")) < today
    )
    return {
        "next_earnings_date": future[0] if future else None,
        "last_reported_date": past[-1] if past else None,
        "coverage": "covered",
    }


def _fetch_calendar(api_key: str) -> dict[str, list[str]] | None:
    """Whole range calendar [today, today+horizon] -> {SYMBOL: [dates]}.
    Cached process-wide (one fetch serves hours of lookups). None on failure."""
    now = time.time()
    with _cache_lock:
        hit = _calendar_cache.get("cal")
        if hit and now - hit[0] < _CACHE_TTL_S and hit[1] is not None:
            return hit[1]
    if not _budget_consume():
        logger.warning("earnings daily budget exhausted; calendar fetch skipped")
        return None
    try:
        start = datetime.now(_ET).date()
        end = start + timedelta(days=_CALENDAR_HORIZON_DAYS)
        resp = requests.get(
            "https://financialmodelingprep.com/stable/earnings-calendar",
            params={"from": start.isoformat(), "to": end.isoformat()},
            headers={"apikey": api_key},
            timeout=20,
        )
        resp.raise_for_status()
        rows = resp.json()
        if not isinstance(rows, list):
            logger.error(f"FMP calendar non-list payload: {str(rows)[:200]}")
            return None
        cal: dict[str, list[str]] = {}
        for r in rows:
            if isinstance(r, dict) and r.get("symbol") and r.get("date"):
                cal.setdefault(str(r["symbol"]).upper(), []).append(str(r["date"]))
        with _cache_lock:
            _calendar_cache["cal"] = (now, cal)
        return cal
    except Exception as e:  # noqa: BLE001
        logger.warning(f"FMP calendar fetch failed: {e}")
        return None


def _calendar_lookup(ticker: str, api_key: str) -> dict[str, Any]:
    """Range-calendar fallback for symbols the per-symbol endpoint won't
    serve on this plan tier."""
    cal = _fetch_calendar(api_key)
    if cal is None:
        return {"error": "earnings provider unreachable — unknown, treat as in-window"}
    dates = sorted(cal.get(ticker, []))
    if dates:
        return {
            "next_earnings_date": dates[0],
            "last_reported_date": None,
            "coverage": "covered_via_calendar",
        }
    return {
        "next_earnings_date": None,
        "last_reported_date": None,
        "coverage": "not_covered_by_plan",
    }


def get_earnings_window(
    ticker: str | None = None,
    expiration: str | None = None,
    contract: str | None = None,
) -> dict[str, Any]:
    """
    Next scheduled earnings date for a ticker, and — given an expiration or an
    OCC contract — whether that print lands ON OR BEFORE the expiration
    (`earnings_in_window`). This is the doctrine hard-exclusion check: never
    hold a long single-leg option through earnings (IV crush). The engine
    applies this rail only at its own pick time, NOT in the pool — pool rows
    CAN carry earnings-window names, so check every candidate yourself.

    One call per candidate: pass the pool's `recommended_contract` verbatim
    and both the ticker and expiration are derived for you.

    FAIL-CLOSED: if the date is unknown (provider gap/outage, unannounced
    small-cap), `earnings_in_window` is null and the response says to treat
    the name as in-window. A confirmed date is still a provider estimate
    until the company confirms — re-check near the date.

    Args:
        ticker: underlying symbol, e.g. "AAPL" (optional if contract given).
        expiration: option expiration "YYYY-MM-DD" to test the window against
            (optional; derived from contract when contract is given).
        contract: OCC-style option ticker (e.g. "O:UNIT260717C00030000") —
            supplies both ticker and expiration in one argument.

    Returns:
        {ticker, next_earnings_date, is_estimated, last_reported_date,
         expiration, earnings_in_window, source, as_of, note}
        — `earnings_in_window`: true (print on/before expiration — doctrine
        says exclude), false (next print is after expiration), or null
        (unknown — treat as in-window).
    """
    if contract is not None:
        m = _CONTRACT_RE.fullmatch(str(contract or "").strip().upper())
        if not m:
            return {
                "error": (
                    "contract must be an OCC-style option ticker like "
                    "'O:TICKER260717C00030000' — pass recommended_contract verbatim"
                )
            }
        ticker = m.group(1)
        yymmdd = m.group(2)
        expiration = f"20{yymmdd[0:2]}-{yymmdd[2:4]}-{yymmdd[4:6]}"

    t = str(ticker or "").strip().upper()
    if not _TICKER_RE.fullmatch(t):
        return {"error": "ticker must be a plain symbol like 'AAPL' (or pass contract=...)"}

    exp = None
    if expiration is not None:
        exp = str(expiration).strip()
        # real calendar parse, not just shape — '2026-00-01' must not silently
        # compare lexicographically into a wrong not-in-window answer (F4)
        try:
            datetime.strptime(exp, "%Y-%m-%d")
        except ValueError:
            return {"error": "expiration must be a real YYYY-MM-DD date (or pass contract=...)"}

    api_key = (os.getenv("FMP_API_KEY") or "").strip()
    if not api_key:
        return {
            "ticker": t,
            "next_earnings_date": None,
            "earnings_in_window": None,
            "error": "earnings-calendar credential not configured on the server",
            "note": _FAIL_CLOSED_NOTE,
        }

    now = time.time()
    with _cache_lock:
        hit = _cache.get(t)
    if hit and now - hit[0] < _CACHE_TTL_S:
        data = hit[1]
    else:
        if not _EARNINGS_BUCKET.try_consume() or not _budget_consume():
            return {
                "ticker": t,
                "next_earnings_date": None,
                "earnings_in_window": None,
                "error": "get_earnings_window rate/daily limit exceeded — try again later",
                "note": _FAIL_CLOSED_NOTE,
            }
        data = _fetch_next_earnings(t, api_key)
        if "error" not in data:
            with _cache_lock:
                if len(_cache) >= 10_000:
                    _cache.clear()
                _cache[t] = (now, data)

    if "error" in data:
        return {
            "ticker": t,
            "next_earnings_date": None,
            "earnings_in_window": None,
            "expiration": exp,
            "error": data["error"],
            "note": _FAIL_CLOSED_NOTE,
        }

    next_date = data.get("next_earnings_date")
    coverage = data.get("coverage") or "unknown"
    out: dict[str, Any] = {
        "ticker": t,
        "next_earnings_date": next_date,
        "is_estimated": True if next_date else None,
        "last_reported_date": data.get("last_reported_date"),
        "coverage": coverage,
        "source": (
            "fmp per-symbol earnings"
            if coverage == "covered"
            else f"fmp range calendar ({_CALENDAR_HORIZON_DAYS}d horizon)"
        ),
        "as_of": datetime.now(_ET).isoformat(timespec="seconds"),
    }
    if exp is not None:
        out["expiration"] = exp

    if next_date is None:
        out["earnings_in_window"] = None
        if coverage == "not_covered_by_plan":
            out["note"] = (
                "This symbol is OUTSIDE the earnings provider's coverage on "
                "the current data plan (typical for small caps) — the date "
                "cannot be determined here. Verify via web search / the "
                "company's IR page. " + _FAIL_CLOSED_NOTE
            )
        else:
            out["note"] = (
                "No upcoming earnings date in the provider's forward window "
                f"(last reported {data.get('last_reported_date') or 'unknown'}). "
                "This can mean 'not yet announced', NOT 'no earnings'. "
                + _FAIL_CLOSED_NOTE
            )
        return out

    calendar_caveat = (
        " (Date came from the sparse range calendar this plan tier serves — "
        "treat a 'clear' verdict from it as thinner evidence than a covered "
        "per-symbol answer.)"
        if coverage == "covered_via_calendar"
        else ""
    )
    if exp is not None:
        out["earnings_in_window"] = next_date <= exp
        out["note"] = (
            (
                f"Earnings {next_date} falls ON/BEFORE expiration {exp} — the "
                "doctrine hard exclusion applies to holds that reach the print. "
                + _ESTIMATE_NOTE
            )
            if out["earnings_in_window"]
            else (
                f"Next earnings {next_date} is AFTER expiration {exp}. "
                + _ESTIMATE_NOTE
                + calendar_caveat
            )
        )
    else:
        out["note"] = _ESTIMATE_NOTE + calendar_caveat
    return out
