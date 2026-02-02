"""
Tool: get_technical_analysis
Get detailed technical analysis for a ticker
"""

import json
import logging

from data.gcs_client import GCSClient

logger = logging.getLogger(__name__)

# Initialize GCS client
gcs_client = GCSClient()


async def get_technical_analysis(ticker: str, as_of: str = "latest") -> str:
    """Get detailed technical analysis including indicators and patterns.

    Returns comprehensive technical analysis from GammaRips'
    technicals_analyzer pipeline with LLM-generated insights.

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL", "TSLA", "NVDA")
        as_of: Date for historical analysis in YYYY-MM-DD format, or "latest" for today (default: "latest")

    Returns:
        JSON string with technical indicators, patterns, and analysis.

    Example:
        >>> result = await get_technical_analysis("NVDA")
        >>> print(result)
        {
          "ticker": "NVDA",
          "as_of": "2026-01-04",
          "analysis": {
            "trend": "Uptrend",
            "rsi_14": 62.5,
            "macd_signal": "Bullish Crossover",
            ...
          }
        }
    """
    try:
        # Validate ticker
        if not ticker or not ticker.strip():
            return json.dumps({"error": "Ticker is required"}, indent=2)

        # Query GCS
        result = await gcs_client.get_technical_analysis(
            ticker=ticker.strip().upper(),
            as_of=as_of,
        )

        return json.dumps(result, indent=2)

    except Exception as e:
        logger.error(f"Error in get_technical_analysis for {ticker}: {e}", exc_info=True)
        return json.dumps(
            {
                "error": f"Failed to fetch technical analysis for {ticker}",
                "details": str(e),
            },
            indent=2,
        )
