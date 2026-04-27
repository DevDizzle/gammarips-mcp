"""
Educational + reference tools for GammaRips MCP.

These are the chat-agent's "ask a dumb question" surface — strict-deterministic
(no LLM, no schema introspection), zero PII risk, intentionally narrow.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from utils.safety import safe_error

logger = logging.getLogger(__name__)


ET = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# get_signal_explainer
# ---------------------------------------------------------------------------
#
# Hardcoded lookup. The chat agent asks "what does premium_score mean?" and
# we return the canonical definition + the role it plays in the V5.3 pipeline.
# No LLM in the path → zero hallucination risk. Add new entries as the agent
# encounters fields it can't explain (rather than blanket-exposing the schema).

_FIELD_EXPLANATIONS: dict[str, dict[str, str]] = {
    "overnight_score": {
        "label": "Overnight Score",
        "definition": (
            "A 1-10 conviction score the overnight scanner assigns to each "
            "ticker based on options-flow concentration, directional UOA, and "
            "implied-vol regime."
        ),
        "how_used": (
            "V5.3 enrichment requires score ≥ 1; the daily pick is chosen from "
            "the top of this ranking after additional liquidity and regime gates."
        ),
    },
    "premium_score": {
        "label": "Premium Score",
        "definition": (
            "A composite quality score combining overnight_score with five "
            "premium-tier flags (liquidity, hedging-ratio, IV-skew, news, "
            "underlying trend)."
        ),
        "how_used": (
            "Used by signal-notifier as a tiebreaker when multiple candidates "
            "clear V5.3 gates. Does NOT call any LLM — fully deterministic."
        ),
    },
    "volume_oi_ratio": {
        "label": "V/OI (Volume / Open-Interest Ratio)",
        "definition": (
            "Today's option volume divided by yesterday's open interest for "
            "the same contract. >1 means more contracts traded today than were "
            "outstanding entering the session — a footprint of new positioning."
        ),
        "how_used": (
            "V5.3 signal-notifier requires V/OI > 2 — strong evidence the "
            "flow is fresh institutional positioning, not stale open interest."
        ),
    },
    "vol_oi_ratio": {
        "label": "V/OI (Volume / Open-Interest Ratio)",
        "definition": (
            "Today's option volume divided by yesterday's open interest. "
            "Synonym for volume_oi_ratio."
        ),
        "how_used": (
            "V5.3 signal-notifier requires V/OI > 2 to qualify a signal as "
            "the daily tradeable pick."
        ),
    },
    "moneyness_pct": {
        "label": "Moneyness % (OTM)",
        "definition": (
            "How far out-of-the-money the recommended contract is, as a "
            "percent of underlying price. 5% = strike is 5% above (calls) or "
            "below (puts) the underlying."
        ),
        "how_used": (
            "V5.3 signal-notifier requires 5% ≤ moneyness ≤ 15%. Closer-to-money "
            "decays slower; farther OTM has more leverage but lower hit rate."
        ),
    },
    "otm_pct": {
        "label": "OTM %",
        "definition": "How far out-of-the-money the strike is, in percent. Synonym for moneyness_pct.",
        "how_used": (
            "V5.3 signal-notifier requires 5% ≤ moneyness ≤ 15%."
        ),
    },
    "recommended_contract": {
        "label": "Recommended Contract",
        "definition": (
            "The OCC-style option contract symbol the V5.3 pipeline picked "
            "for the trade — e.g. O:NVDA260516C00130000 = NVDA $130 call "
            "expiring 2026-05-16."
        ),
        "how_used": (
            "Resolved by the enrichment service from {underlying, direction, "
            "DTE 7-14, 5-15% OTM, ≤10% spread}. Not user-modifiable."
        ),
    },
    "recommended_strike": {
        "label": "Recommended Strike",
        "definition": "Strike price of the recommended contract (in dollars).",
        "how_used": "Resolved automatically alongside recommended_contract.",
    },
    "recommended_expiration": {
        "label": "Recommended Expiration",
        "definition": "Expiration date of the recommended contract.",
        "how_used": (
            "Picked to land DTE in the 7-14 day window — short enough for "
            "convexity, long enough to survive the 3-day hold without theta "
            "ramp."
        ),
    },
    "recommended_dte": {
        "label": "DTE (Days To Expiration)",
        "definition": "Calendar days from the recommended_expiration to scan_date.",
        "how_used": (
            "V5.3 enrichment targets DTE 7-14. Below 7 → theta ramp dominates "
            "in the 3-day hold. Above 14 → wastes capital on time the strategy "
            "doesn't need."
        ),
    },
    "recommended_mid_price": {
        "label": "Recommended Mid Price",
        "definition": (
            "(bid + ask) / 2 of the recommended contract at the moment of "
            "enrichment (~05:30 ET)."
        ),
        "how_used": (
            "Display-only. The paper-trader DOES NOT use this for entry — it "
            "uses the actual D+1 10:00 ET fill from Polygon. Never extrapolate "
            "performance from this number."
        ),
    },
    "recommended_spread_pct": {
        "label": "Spread %",
        "definition": "(ask - bid) / mid for the recommended contract, expressed as a percent.",
        "how_used": (
            "V5.3 enrichment requires spread ≤ 10%. Wider spreads kill the "
            "expected value of a −60/+80 bracket on small contracts."
        ),
    },
    "call_dollar_volume": {
        "label": "Call Dollar Volume (Directional UOA)",
        "definition": (
            "Today's notional dollar volume in calls — number of contracts "
            "traded × premium × 100. Captures the dollar weight of bullish "
            "options activity."
        ),
        "how_used": (
            "V5.3 enrichment requires directional UOA > $500K. Filters out "
            "low-conviction or coincidentally-traded names."
        ),
    },
    "put_dollar_volume": {
        "label": "Put Dollar Volume (Directional UOA)",
        "definition": "Today's notional dollar volume in puts. Bearish-direction analog of call_dollar_volume.",
        "how_used": "Same gate threshold as call_dollar_volume — directional UOA > $500K.",
    },
    "vix3m_at_enrich": {
        "label": "VIX3M (at enrichment time)",
        "definition": "Forward 3-month VIX at the moment of enrichment (~05:30 ET on the entry date).",
        "how_used": (
            "V5.3 regime gate: signal-notifier requires VIX(now) ≤ VIX3M. "
            "Backwardation (spot > forward) means traders are pricing imminent "
            "vol → adverse regime for our 3-day directional trade."
        ),
    },
    "vix_now_at_decision": {
        "label": "VIX (at decision time)",
        "definition": "Spot VIX at the moment of signal-notifier decision (~09:00 ET).",
        "how_used": (
            "Compared to vix3m_at_enrich for the regime gate. If spot > forward "
            "(backwardation) we skip the day with skip_reason='vix_backwardation'."
        ),
    },
    "is_premium_signal": {
        "label": "Premium Signal Flag",
        "definition": "Boolean: did the signal pass all 5 premium-tier flags AND clear V5.3 gates?",
        "how_used": (
            "Used as a tiebreaker if multiple signals clear V5.3 gates on the "
            "same morning. Premium-flagged signals are preferred."
        ),
    },
    "key_headline": {
        "label": "Key Headline",
        "definition": "Short news headline (when present) the enrichment pipeline associated with this name.",
        "how_used": "Optional context only — does NOT factor into the gate or the pick decision.",
    },
}


def get_signal_explainer(field_name: str) -> dict[str, Any]:
    """
    Return a plain-English definition + role of a GammaRips signal field.

    Deterministic lookup table — no LLM, no hallucination. Use this for the
    "what does X mean?" pattern when a chat user asks about a metric we
    surfaced. If the field isn't in our dictionary, returns an "unknown" row
    rather than guessing.

    Args:
        field_name: Field name as it appears in tool responses (e.g.,
            "premium_score", "volume_oi_ratio", "recommended_contract").

    Returns:
        {field_name, label, definition, how_used, available_fields}
        — `available_fields` is the full list of supported field names so the
        agent can offer alternatives if the input was misspelled.
    """
    key = (field_name or "").strip().lower()
    entry = _FIELD_EXPLANATIONS.get(key)
    if entry is None:
        return {
            "field_name": field_name,
            "label": None,
            "definition": (
                f"No explanation available for '{field_name}'. This may be an "
                "internal field, a typo, or a metric outside the GammaRips "
                "public API surface."
            ),
            "how_used": None,
            "available_fields": sorted(_FIELD_EXPLANATIONS.keys()),
        }
    return {
        "field_name": key,
        **entry,
        "available_fields": sorted(_FIELD_EXPLANATIONS.keys()),
    }


# ---------------------------------------------------------------------------
# get_market_calendar_status
# ---------------------------------------------------------------------------

def get_market_calendar_status() -> dict[str, Any]:
    """
    Returns whether the US equity market is open today + the next open/close.
    Uses pandas_market_calendars (NYSE) so it knows about holidays + early
    closes deterministically — eliminates the chat-agent "is the market
    open?" hallucination class.

    Returns:
        {
          "is_open_today": bool,
          "current_date": "YYYY-MM-DD" (Eastern),
          "current_time_et": "ISO8601" (Eastern),
          "next_open": "ISO8601" (Eastern, schedule open boundary),
          "next_close": "ISO8601" (Eastern, schedule close boundary),
          "is_holiday": bool,
          "holiday_name": str | None,
          "is_early_close": bool,
        }
    """
    try:
        import pandas as pd
        import pandas_market_calendars as mcal
    except ImportError as e:
        return {"error": safe_error(e, "get_market_calendar_status (import)")}

    try:
        nyse = mcal.get_calendar("XNYS")
        now_et = datetime.now(ET)
        today_iso = now_et.date().isoformat()

        # Schedule for a 14-day window so we can locate the next open even on
        # a long-weekend or holiday boundary.
        start = (now_et.date()).isoformat()
        end = (now_et.date() + pd.Timedelta(days=14)).isoformat()
        sched = nyse.schedule(start_date=start, end_date=end)

        is_open_today = today_iso in sched.index.strftime("%Y-%m-%d").tolist()

        # Holiday detection: if today is a weekday but not in the schedule,
        # it's a holiday. Get the holiday name from pandas_market_calendars'
        # holiday calendar.
        is_holiday = False
        holiday_name: str | None = None
        if now_et.weekday() < 5 and not is_open_today:
            try:
                holiday_calendar = nyse.holidays()
                # NYSE returns a CustomBusinessDay calendar — the .holidays
                # attribute on it is a numpy array of holiday dates with names
                # in `.holidays`.
                today_np = pd.Timestamp(now_et.date())
                if today_np in holiday_calendar.holidays:
                    is_holiday = True
                    # Best-effort holiday name — pandas_market_calendars exposes
                    # named holidays via `nyse.special_dates()` which returns a
                    # DataFrame with `name` column.
                    try:
                        special = nyse.special_dates(
                            "holidays", start_date=start, end_date=end
                        )
                        match = special[special.index == today_np]
                        if not match.empty:
                            holiday_name = str(match.iloc[0])
                    except Exception:  # noqa: BLE001
                        pass
            except Exception:  # noqa: BLE001
                pass

        # Determine next open / next close.
        if sched.empty:
            return {
                "is_open_today": False,
                "current_date": today_iso,
                "current_time_et": now_et.isoformat(),
                "next_open": None,
                "next_close": None,
                "is_holiday": is_holiday,
                "holiday_name": holiday_name,
                "is_early_close": False,
            }

        # `sched` rows have market_open + market_close columns (UTC tz-aware).
        next_open_utc = None
        next_close_utc = None
        is_early_close = False
        for ts, row in sched.iterrows():
            mo = row["market_open"].to_pydatetime().astimezone(timezone.utc)
            mc = row["market_close"].to_pydatetime().astimezone(timezone.utc)
            now_utc = now_et.astimezone(timezone.utc)
            if next_open_utc is None and mo > now_utc:
                next_open_utc = mo
            if next_close_utc is None and mc > now_utc:
                next_close_utc = mc
                # Compare close in ET local time so it works year-round (EST
                # vs EDT) — a regular session ends at 16:00 ET. Anything earlier
                # is an early-close day (e.g. day-after-Thanksgiving 13:00 ET).
                mc_et = mc.astimezone(ET)
                if mc_et.hour < 16 or (mc_et.hour == 16 and mc_et.minute < 0):
                    is_early_close = True
            if next_open_utc and next_close_utc:
                break

        return {
            "is_open_today": bool(is_open_today),
            "current_date": today_iso,
            "current_time_et": now_et.isoformat(timespec="seconds"),
            "next_open": next_open_utc.astimezone(ET).isoformat(timespec="minutes")
            if next_open_utc
            else None,
            "next_close": next_close_utc.astimezone(ET).isoformat(timespec="minutes")
            if next_close_utc
            else None,
            "is_holiday": bool(is_holiday),
            "holiday_name": holiday_name,
            "is_early_close": bool(is_early_close),
        }

    except Exception as e:
        return {"error": safe_error(e, "get_market_calendar_status")}
