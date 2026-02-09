"""
Tool: get_top_picks_analysis
Orchestrates the full trading analysis playbook to find and score top options picks.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

from tools.fundamental_deep_dive import get_macro_thesis
from tools.market_events import get_market_events
from tools.market_structure import analyze_market_structure
from tools.news_analysis import get_news_analysis
from tools.technical_analysis import get_technical_analysis
from tools.winners_dashboard import get_winners_dashboard

logger = logging.getLogger(__name__)


async def get_top_picks_analysis(
    limit: int = 3,
    include_macro: bool = True,
    option_type: str | None = None,
) -> str:
    """Get fully analyzed top options picks with all supporting data.

    Runs the complete analysis playbook:
    1. Checks macro context
    2. Pulls signal universe from winners dashboard
    3. Filters for quality and volatility
    4. Deep dives candidates (news, technicals, market structure, events)
    5. Scores and ranks candidates based on conviction

    Args:
        limit: Number of top picks to return (default: 3)
        include_macro: Whether to include macro thesis (default: True)
        option_type: Filter by "CALL" or "PUT" (default: both)

    Returns:
        JSON string with structured analysis, top picks, and runners up.
    """
    try:
        # --- Step 1: Macro Context ---
        macro_context = {}
        if include_macro:
            try:
                macro_json = await get_macro_thesis()
                macro_context = json.loads(macro_json)
            except Exception as e:
                logger.error(f"Failed to get macro thesis: {e}")
                macro_context = {"error": "Failed to retrieve macro context"}

        # --- Step 2: Signal Universe ---
        # Request all daily signals (limit=50 covers typical daily volume of ~35-40)
        dashboard_json = await get_winners_dashboard(limit=50, option_type=option_type)
        dashboard = json.loads(dashboard_json)
        
        if "signals" not in dashboard:
            return json.dumps(
                {"error": "No signals found in dashboard", "raw_response": dashboard}, indent=2
            )

        all_signals = dashboard["signals"]

        # --- Step 3: Filter Candidates ---
        # Filter: Strong quality AND Cheap/Fair volatility
        # Note: Data uses "Strong" for quality, and specific vol terms
        valid_volatility = [
            "Cheap",
            "Fair",
            "Fairly Priced",
            "Undervalued",
            "Favorable",
        ]

        candidates = []
        for sig in all_signals:
            quality = sig.get("setup_quality_signal", "")
            volatility = sig.get("volatility_comparison_signal", "")
            
            # Relaxed quality check: Accept "High" (legacy) or "Strong"
            is_quality = quality in ["Strong", "High"]
            is_good_vol = volatility in valid_volatility
            
            if is_quality and is_good_vol:
                candidates.append(sig)

        # Analyze ALL qualified candidates (no arbitrary limit)
        deep_dive_candidates = candidates
        
        if not deep_dive_candidates:
            # Fallback: if no "Strong" signals, take top "Medium" ones to provide *something*
            logger.warning("No Strong/Cheap signals found. Falling back to top dashboard results.")
            deep_dive_candidates = all_signals[:5]

        # --- Step 4: Deep Dive (Parallel with Semaphore) ---
        # Use semaphore to limit concurrent requests to avoid timeouts/rate limits
        sem = asyncio.Semaphore(10)

        async def analyze_candidate(signal):
            async with sem:
                ticker = signal.get("ticker")
                if not ticker:
                    return None

                # Run all deep dive tools in parallel
                results = await asyncio.gather(
                    get_news_analysis(ticker),
                    get_technical_analysis(ticker),
                    analyze_market_structure(ticker),
                    get_market_events(ticker=ticker, days_forward=5),
                    return_exceptions=True
                )

                # Parse results safely
                news = _parse_result(results[0])
                technicals = _parse_result(results[1])
                structure = _parse_result(results[2])
                events = _parse_result(results[3])

                return {
                    "signal": signal,
                    "news": news,
                    "technicals": technicals,
                    "structure": structure,
                    "events": events
                }

        analyzed_candidates = await asyncio.gather(
            *[analyze_candidate(c) for c in deep_dive_candidates]
        )
        analyzed_candidates = [c for c in analyzed_candidates if c]

        # --- Step 5: Scoring ---
        scored_candidates = []
        disqualified = []

        for item in analyzed_candidates:
            score, reasons, is_disqualified, disqualify_reason = _score_candidate(item)
            
            candidate_data = {
                "ticker": item["signal"].get("ticker"),
                "contract": {
                    "type": item["signal"].get("option_type"),
                    "strike": item["signal"].get("strike"),
                    "expiration": item["signal"].get("expiration"),
                },
                "current_price": item["signal"].get("current_price"),
                "conviction_score": score,
                "quality": item["signal"].get("setup_quality_signal"),
                "volatility": item["signal"].get("volatility_comparison_signal"),
                "thesis": item["news"].get("analysis", {}).get("catalyst_type", "Technical Setup"),
                "supporting_analysis": {
                    "news": item["news"],
                    "technicals": item["technicals"],
                    "market_structure": item["structure"],
                    "events": item["events"]
                },
                "score_breakdown": reasons
            }

            if is_disqualified:
                disqualified.append({
                    "ticker": candidate_data["ticker"],
                    "reason": disqualify_reason
                })
            else:
                scored_candidates.append(candidate_data)

        # Sort by score descending
        scored_candidates.sort(key=lambda x: x["conviction_score"], reverse=True)

        # --- Step 6: Construct Output ---
        top_picks = scored_candidates[:limit]
        runners_up = scored_candidates[limit:]

        output = {
            "analysis_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "analysis_time_utc": datetime.now(timezone.utc).strftime("%H:%M:%S"),
            "macro_context": macro_context,
            "top_picks": top_picks,
            "runners_up": runners_up,
            "avoid": disqualified,
            "candidates_analyzed": len(analyzed_candidates),
            "candidates_qualified": len(scored_candidates)
        }

        return json.dumps(output, indent=2)

    except Exception as e:
        logger.error(f"Error in get_top_picks_analysis: {e}", exc_info=True)
        return json.dumps({"error": str(e)}, indent=2)


def _parse_result(result):
    """Helper to parse JSON string results, handling exceptions."""
    if isinstance(result, Exception):
        logger.error(f"Task failed: {result}")
        return {}
    try:
        return json.loads(result)
    except:
        return {}


def _score_candidate(item):
    """Score a candidate based on the playbook rubric.
    
    Returns:
        tuple: (score, reasons_list, is_disqualified, disqualify_reason)
    """
    score = 0
    reasons = []
    
    signal = item["signal"]
    news = item["news"].get("analysis", {})
    tech = item["technicals"].get("analysis", {})
    struct = item["structure"].get("summary", {})
    events = item["events"].get("events", [])

    # 1. Earnings Check (Disqualifier)
    # Check if any event is 'Earnings'
    for e in events:
        if e.get("event_type") == "Earnings":
            return 0, [], True, f"Earnings on {e.get('event_date')}"

    # 2. Volatility Assessment (0-10)
    vol = signal.get("volatility_comparison_signal", "")
    if vol in ["Cheap", "Undervalued"]:
        score += 10
        reasons.append("Cheap volatility (+10)")
    elif vol in ["Fair", "Fairly Priced"]:
        score += 7
        reasons.append("Fair volatility (+7)")
    else:
        reasons.append(f"Volatility {vol} (+0)")

    # 3. Catalyst/News (0-10)
    sent_score = news.get("sentiment_score", 0.5)
    if sent_score >= 0.7:
        score += 8
        reasons.append("Strong bullish sentiment (+8)")
    elif sent_score >= 0.5:
        score += 5
        reasons.append("Positive/Neutral sentiment (+5)")
    else:
        reasons.append("Weak sentiment (+0)")
        
    # Bonus for specific catalyst
    if news.get("catalyst_type") and news.get("catalyst_type") != "None":
        score += 2
        reasons.append("Identified Catalyst (+2)")

    # 4. Technical Score (0-10)
    # Assume technical_score is 0-1 or 0-100. Normalize to 0-10.
    # If missing, try to infer from trend.
    tech_score_raw = tech.get("technical_score")
    if tech_score_raw is not None:
        if tech_score_raw <= 1.0:
            tech_points = tech_score_raw * 10
        else:
            tech_points = tech_score_raw / 10
        score += int(tech_points)
        reasons.append(f"Technical score {tech_points:.1f} (+{int(tech_points)})")
    else:
        # Fallback logic
        trend = tech.get("trend", "Neutral")
        if "Uptrend" in trend and signal.get("option_type") == "CALL":
            score += 7
            reasons.append("Trend alignment (+7)")
        elif "Downtrend" in trend and signal.get("option_type") == "PUT":
            score += 7
            reasons.append("Trend alignment (+7)")
        else:
            score += 4 # Neutral
            reasons.append("Neutral/Unknown technicals (+4)")

    # 5. Options Flow (0-10)
    # Low Put/Call Ratio (Volume) favors Calls (< 0.7)
    # High Put/Call Ratio favors Puts (> 1.0) -- rough heuristic
    pcr_vol = struct.get("put_call_ratio_volume")
    option_type = signal.get("option_type")
    
    flow_score = 5 # Start neutral
    if pcr_vol is not None:
        if option_type == "CALL":
            if pcr_vol < 0.7: flow_score = 9
            elif pcr_vol < 1.0: flow_score = 7
            else: flow_score = 3
        elif option_type == "PUT":
            if pcr_vol > 1.2: flow_score = 9
            elif pcr_vol > 1.0: flow_score = 7
            else: flow_score = 3
            
    score += flow_score
    reasons.append(f"Flow PCR {pcr_vol} for {option_type} (+{flow_score})")

    # 6. Room to Run (0-10)
    # Hard to calculate without ATR/Resistance distance. 
    # We'll give a baseline based on "setup_quality" from dashboard
    quality = signal.get("setup_quality_signal")
    if quality in ["Strong", "High"]:
        score += 8
        reasons.append("Strong Setup Quality (+8)")
    elif quality == "Medium":
        score += 5
        reasons.append("Medium Setup Quality (+5)")
    else:
        score += 2
        reasons.append("Low Setup Quality (+2)")

    # Final Qualification
    if score < 30: # Relaxed from 35 to ensure we get some output
        return score, reasons, True, f"Low Score ({score})"
    
    return score, reasons, False, None
