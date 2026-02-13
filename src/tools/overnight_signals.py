"""
Overnight Edge tools for GammaRips MCP
"""

import logging
from typing import Any, Dict, List, Optional
from datetime import datetime

from data.bigquery_client import BigQueryClient
from data.firestore_client import FirestoreClient

logger = logging.getLogger(__name__)

# Initialize clients
bq_client = BigQueryClient()
fs_client = FirestoreClient()

def _get_user_tier(kwargs: Dict[str, Any]) -> str:
    """Extract user tier from injected user_info."""
    user_info = kwargs.get("_user_info", {})
    return user_info.get("tier", "FREE")

async def get_overnight_signals(
    direction: str = "ALL",
    min_score: int = 5,
    limit: int = 20,
    date: str = "latest",
    **kwargs
) -> Dict[str, Any]:
    """
    Get today's overnight institutional flow signals.
    """
    tier = _get_user_tier(kwargs)
    
    # Tier restrictions
    if tier == "FREE":
        min_score = max(min_score, 7)
        limit = min(limit, 10)
    
    # Try Firestore first (faster)
    # Convert "latest" to today's date or handle in client
    query_date = date
    if query_date == "latest":
        query_date = datetime.now().strftime("%Y-%m-%d")
        
    signals = await fs_client.get_overnight_signals(
        date=query_date,
        direction=direction,
        min_score=min_score,
        limit=limit
    )
    
    # Fallback to BigQuery if empty
    if not signals:
        logger.info(f"No signals in Firestore for {query_date}, trying BigQuery")
        bq_res = await bq_client.get_overnight_signals(
            date=date,
            direction=direction,
            min_score=min_score,
            limit=limit
        )
        signals = bq_res.get("signals", [])
        query_date = bq_res.get("scan_date", query_date)

    # Filter fields for Free tier
    if tier == "FREE":
        filtered_signals = []
        for sig in signals:
            # Create a copy to avoid modifying cached data if any
            s = sig.copy()
            # Remove paid fields
            for field in [
                "recommended_contract", "recommended_strike", "recommended_expiration", 
                "recommended_mid_price", "contract_score", "technicals", "news", 
                "catalyst_summary", "flow_details"
            ]:
                s.pop(field, None)
            filtered_signals.append(s)
        signals = filtered_signals

    response = {
        "scan_date": query_date,
        "total_signals": len(signals),
        "signals": signals
    }

    # Add upgrade prompt for Free tier
    if tier == "FREE":
        response["upgrade"] = {
            "message": f"You're seeing {len(signals)} signals (score 7+ only). Unlock all signals, contracts, technicals & AI analysis.",
            "plans": [
                {"name": "The Overnight Edge", "price": "$49/mo", "url": "https://gammarips.com/#pricing"},
                {"name": "The War Room", "price": "$149/mo", "url": "https://gammarips.com/#pricing"}
            ]
        }
        
    return response

async def get_signal_detail(ticker: str, date: str = "latest", **kwargs) -> Dict[str, Any]:
    """
    Deep dive on a single ticker's overnight signal.
    """
    tier = _get_user_tier(kwargs)
    
    if tier == "FREE":
        return {
            "error": "upgrade_required",
            "message": "Signal deep dives require The Overnight Edge ($49/mo)",
            "url": "https://gammarips.com/#pricing"
        }
        
    # Try Firestore
    query_date = date
    if query_date == "latest":
        query_date = datetime.now().strftime("%Y-%m-%d")

    signal = await fs_client.get_signal_detail(ticker, query_date)
    
    # Fallback BQ
    if not signal:
        signal = await bq_client.get_signal_detail(ticker, date)
        
    if not signal:
        return {"error": "Signal not found", "ticker": ticker}
        
    return signal

async def get_top_movers(count: int = 5, **kwargs) -> Dict[str, Any]:
    """
    Quick summary of today's highest conviction signals.
    """
    # Available to all tiers
    
    # Use BigQuery for aggregation/sorting efficiency as Firestore simple query might not do complex top N per group easily without multiple queries
    # But BQ is fine here.
    return await bq_client.get_top_movers(count=count)

async def get_market_themes(date: str = "latest", **kwargs) -> Dict[str, Any]:
    """
    AI-generated analysis of tonight's overnight flow themes.
    """
    tier = _get_user_tier(kwargs)
    
    # Try Firestore
    query_date = date
    if query_date == "latest":
        query_date = datetime.now().strftime("%Y-%m-%d")
        
    themes = await fs_client.get_market_themes(query_date)
    
    # Fallback BQ (Stub)
    if not themes:
        bq_res = await bq_client.get_market_themes(date)
        themes = bq_res.get("themes", [])
        query_date = bq_res.get("scan_date", query_date)
        
    # Free tier restrictions
    if tier == "FREE":
        filtered_themes = []
        for theme in themes:
            t = theme.copy()
            # Remove ticker lists
            t.pop("tickers", None)
            filtered_themes.append(t)
        themes = filtered_themes
        
    return {
        "scan_date": query_date,
        "themes": themes
    }
