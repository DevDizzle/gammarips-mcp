"""
Educational + reference tools for GammaRips MCP.

These are the chat-agent's "ask a dumb question" surface — strict-deterministic
(no LLM, no schema introspection), zero PII risk, intentionally narrow.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
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
# we return the canonical definition + the role it plays in the V6 pipeline.
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
            "Enrichment requires score ≥ 4; the engine's own daily selection is "
            "drawn from this pool after the BULLISH-only gate, a delta edge-rank "
            "to the top ~50, two safety rails (no earnings in the exclusion "
            "window; VIX ≤ VIX3M), and a randomized 3-bracket consensus "
            "tournament (a pattern your agent can run itself — see "
            "get_playbook('run-your-own-tournament'))."
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
            "Deterministic composite (no LLM). A legacy ranking aid retained for "
            "context; the V6 pick is decided by the bracket tournament, not by "
            "this score."
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
            "A high V/OI is evidence the flow is fresh institutional positioning "
            "rather than stale open interest. NOTE: V/OI is no longer a selection "
            "gate under V6 — it was retired because the overnight UOA spike does "
            "not become open interest until the next session. It survives as "
            "descriptive context only."
        ),
    },
    "vol_oi_ratio": {
        "label": "V/OI (Volume / Open-Interest Ratio)",
        "definition": (
            "Today's option volume divided by yesterday's open interest. "
            "Synonym for volume_oi_ratio."
        ),
        "how_used": (
            "Descriptive context only. Synonym for volume_oi_ratio — no longer a V6 selection gate."
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
            "Closer-to-money decays slower; farther OTM has more leverage but a "
            "lower hit rate. NOTE: the old 5–15% OTM moneyness gate was retired "
            "under V6 — moneyness is no longer a hard selection filter. Contract "
            "choice is delta-driven (a mid-|delta| 0.20–0.46 edge prior)."
        ),
    },
    "otm_pct": {
        "label": "OTM %",
        "definition": "How far out-of-the-money the strike is, in percent. Synonym for moneyness_pct.",
        "how_used": ("Descriptive context only — no longer a V6 selection gate."),
    },
    "recommended_contract": {
        "label": "Recommended Contract",
        "definition": (
            "The OCC-style option contract symbol the V6 pipeline picked "
            "for the trade — e.g. O:NVDA260516C00130000 = NVDA $130 call "
            "expiring 2026-05-16."
        ),
        "how_used": (
            "Resolved by the enrichment service for the chosen BULLISH name "
            "(delta-driven strike, short-DTE). Not user-modifiable."
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
            "convexity, long enough that theta doesn't dominate a short hold."
        ),
    },
    "recommended_dte": {
        "label": "DTE (Days To Expiration)",
        "definition": "Calendar days from the recommended_expiration to scan_date.",
        "how_used": (
            "Enrichment targets a short DTE (roughly 7-14 days). Below ~7 → "
            "theta ramp dominates even a short hold. Well above → wastes "
            "capital on time a short-horizon trade doesn't need."
        ),
    },
    "recommended_mid_price": {
        "label": "Recommended Mid Price",
        "definition": (
            "(bid + ask) / 2 of the recommended contract at the moment of enrichment (~05:30 ET)."
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
            "Historically used as a ≤10% spread gate. RETIRED under V6 — the "
            "current Polygon data plan serves no live option quotes, so spread is "
            "permanently NULL and contracts price off last-trade / day-close. No "
            "longer a selection gate."
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
            "V6 enrichment requires directional UOA > $500K. Filters out "
            "low-conviction or coincidentally-traded names. Calls drive the live "
            "BULLISH-only strategy."
        ),
    },
    "put_dollar_volume": {
        "label": "Put Dollar Volume (Directional UOA)",
        "definition": "Today's notional dollar volume in puts. Bearish-direction analog of call_dollar_volume.",
        "how_used": (
            "Same $500K enrichment threshold as call_dollar_volume. NOTE: the live "
            "V6 strategy trades BULLISH calls only, so put-side rows appear in "
            "historical data but are not currently selectable."
        ),
    },
    "vix3m_at_enrich": {
        "label": "VIX3M (at enrichment time)",
        "definition": "Forward 3-month VIX at the moment of enrichment (~05:30 ET on the entry date).",
        "how_used": (
            "Regime safety rail: the engine requires VIX(now) ≤ VIX3M. "
            "Backwardation (spot > forward) means traders are pricing imminent "
            "vol → adverse regime for short-dated directional longs. See "
            "get_regime_context."
        ),
    },
    "vix_now_at_decision": {
        "label": "VIX (at decision time)",
        "definition": "Spot VIX at the moment of signal-notifier decision (~07:30 ET).",
        "how_used": (
            "Compared to vix3m_at_enrich for the regime gate. If spot > forward "
            "(backwardation) we skip the day with skip_reason='vix_backwardation'."
        ),
    },
    "is_premium_signal": {
        "label": "Premium Signal Flag",
        "definition": "Boolean: did the signal pass all 5 premium-tier flags AND clear enrichment?",
        "how_used": (
            "A legacy quality flag retained for context. Under V6 the daily pick "
            "is decided by the bracket tournament, not by this flag."
        ),
    },
    "key_headline": {
        "label": "Key Headline",
        "definition": "Short news headline (when present) the enrichment pipeline associated with this name.",
        "how_used": "Optional context only — does NOT factor into the gate or the pick decision.",
    },
    "mom_60": {
        "label": "60-Day Momentum",
        "definition": (
            "Underlying price momentum over the trailing ~60 trading days, as a "
            "fraction (0.35 = +35%). Point-in-time-guarded: both anchor and "
            "lookback dates are <= scan_date."
        ),
        "how_used": (
            "A research lever, not a rule: historically mom_60 ≥ +0.35 combined "
            "with mid-|delta| 0.20-0.46 beat the bullish baseline UNDER THE 3-DAY "
            "horizon, with no edge under the same-day bracket. Exit-conditional — "
            "validate on your own horizon via query_outcomes before leaning on it."
        ),
    },
    "opp_peak_return": {
        "label": "Opportunity Peak (MFE)",
        "definition": (
            "Max FAVORABLE excursion: the highest the option premium traded above "
            "the 10:00 ET entry cost basis during the 3-trading-day window, as a "
            "fraction (0.40 = +40%). No exit rule applied."
        ),
        "how_used": (
            "The core of the opportunity surface — profit POTENTIAL with the exit "
            "left free. Timing fact (measured Apr-Jun 2026): peaks >= +20% land "
            "on day 1 only ~15% of the time; day 3 ~52% — plan exits for the back "
            "of the window. Realized post-entry: never use as a selection "
            "feature. See get_opportunity_surface, get_harvest_curve, and "
            "get_playbook('exit-lab')."
        ),
    },
    "opp_trough_return": {
        "label": "Opportunity Trough (MAE)",
        "definition": (
            "Max ADVERSE excursion: the lowest the option premium traded below the "
            "entry cost basis during the 3-trading-day window, as a fraction "
            "(-0.30 = -30%). No exit rule applied."
        ),
        "how_used": (
            "Bounds the pain any exit rule must survive. Realized post-entry: "
            "never use as a selection feature."
        ),
    },
    "opp_status": {
        "label": "Opportunity Surface Status",
        "definition": (
            "State of the excursion computation: OK (window closed, MFE/MAE "
            "final), WINDOW_OPEN (still inside the 3-day window), NO_BARS / "
            "INVALID_LIQUIDITY (no tradeable prints), and error states."
        ),
        "how_used": "Only opp_status='OK' rows have final excursions; tools default to them.",
    },
    "realized_return_pct": {
        "label": "Same-Day Bracket Label",
        "definition": (
            "Realized option return, as a FRACTION, under the live same-day GIGO "
            "bracket: enter 10:00 ET the day after scan, +40% target / -30% stop, "
            "flat 15:45 ET. TIMEOUT > STOP > TARGET on ambiguous bars."
        ),
        "how_used": (
            "The canonical same-day label for research (query_outcomes horizon="
            "'same_day') and the paper cohort's realized result in the receipts. "
            "A LABEL — realized post-entry, never a selection input."
        ),
    },
    "realized_return_pct_3d": {
        "label": "3-Day Bracket Label",
        "definition": (
            "Realized option return, as a FRACTION, under the legacy 3-trading-day "
            "companion bracket: +80% target / -60% stop, exit 15:50 ET on day 3."
        ),
        "how_used": (
            "A separate label horizon (query_outcomes horizon='3d') — never pool "
            "or compare it with same-day labels. Where the mom_60 x delta research "
            "lead lives."
        ),
    },
    "vix_at_scan": {
        "label": "VIX (as-of scan date)",
        "definition": "Spot VIX close as-of the scan date — known before any entry decision.",
        "how_used": (
            "The leakage-safe regime FEATURE (vs oc_* telemetry, which is entry-"
            "day close and realized after the trade). Compared against "
            "vix3m_at_enrich for the regime rail. See get_regime_context."
        ),
    },
    "spy_trend_at_scan": {
        "label": "SPY Trend State (as-of scan date)",
        "definition": "Categorical SPY trend regime (e.g. above/below key moving averages) as-of the scan date.",
        "how_used": "Point-in-time regime feature for conditioning research; not a hard gate.",
    },
    "illiquid_exit": {
        "label": "Illiquid Exit Flag",
        "definition": (
            "TRUE when the simulated exit had no tradeable print near the exit "
            "time, so the label is unreliable."
        ),
        "how_used": (
            "Excluded from EV/aggregate tools by default (exclusion counts are "
            "reported in meta). The illiquid tail (~28% of the pool) is "
            "non-random — always report it alongside conclusions."
        ),
    },
    "exit_slippage": {
        "label": "Exit Slippage",
        "definition": "Fill-realism haircut applied at the simulated exit, as a fraction of premium.",
        "how_used": (
            "Part of why exact bracket labels sit below raw opportunity-surface "
            "estimates (the surface applies entry slippage only)."
        ),
    },
    "recommended_oi": {
        "label": "Open Interest (scan-time snapshot)",
        "definition": (
            "PRIOR-SESSION open interest for the recommended contract, frozen at "
            "scan time. NOT live OI — overnight sweeps typically become visible "
            "OI only the next morning."
        ),
        "how_used": (
            "A point-in-time feature but a STALE liquidity signal. Re-check live "
            "liquidity with get_contract_snapshot (fresh OI / session volume / "
            "last trade) before sizing a real trade."
        ),
    },
    "recommended_volume": {
        "label": "Contract Volume (scan-time snapshot)",
        "definition": "Cumulative session volume for the recommended contract, frozen at scan time.",
        "how_used": (
            "Same staleness caveat as recommended_oi — feature, not live "
            "liquidity. get_contract_snapshot serves the fresh values."
        ),
    },
    "recommended_delta": {
        "label": "Contract Delta (scan-time)",
        "definition": (
            "The recommended contract's option delta as-of scan time. Delta is "
            "also, approximately, the market-implied probability the contract "
            "expires in the money."
        ),
        "how_used": (
            "Treat |delta| as your honest BASE RATE: on 2,146 expired pool "
            "contracts (Apr-Jun 2026) the realized ITM rate was 41.3% vs a mean "
            "delta of 42.1% — the pool converts at the market-implied rate, so a "
            "0.35-delta candidate is a ~1-in-3 proposition at expiry no matter "
            "how good the narrative reads. Historically the mid band "
            "(|delta| 0.20-0.46) was the strongest conditional lever on 3-day "
            "labels."
        ),
    },
    "harvest_curve": {
        "label": "Harvest Curve (concept)",
        "definition": (
            "P(the option's premium touches +X% at least once within the "
            "3-trading-day window from the 10:00 ET entry), for a grid of "
            "targets X — the ceiling for any limit-at-+X% exit."
        ),
        "how_used": (
            "Served live by get_harvest_curve. Measured on the Apr-Jun 2026 pool: "
            "~half of contracts touch +20%, ~1 in 7 touches +100%, and the "
            "meaningful pops land on day 2-3, not day 1. A touch is not a fill — "
            "treat the curve as an upper bound."
        ),
    },
    "giveback": {
        "label": "Giveback (concept)",
        "definition": (
            "How much of a contract's peak gain evaporates by expiration if "
            "nobody exits: peak return minus terminal return."
        ),
        "how_used": (
            "The measured reason exit discipline matters: conditional on touching "
            "+50%, the median pool contract retained only ~31% of its peak at "
            "expiry, and ~48% of all ever-profitable contracts expired at a loss "
            "(Apr-Jun 2026, N=1,303 expired; the 31% figure conditions on the N=571 subset that touched +50%). The surface is real; holding surrenders it."
        ),
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
                        special = nyse.special_dates("holidays", start_date=start, end_date=end)
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
        for _ts, row in sched.iterrows():
            mo = row["market_open"].to_pydatetime().astimezone(UTC)
            mc = row["market_close"].to_pydatetime().astimezone(UTC)
            now_utc = now_et.astimezone(UTC)
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
