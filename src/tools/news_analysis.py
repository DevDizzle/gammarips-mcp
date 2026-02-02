"""
Tool: get_news_analysis
Get news sentiment and catalyst analysis for a ticker
"""

import json
import logging

from data.gcs_client import GCSClient

logger = logging.getLogger(__name__)

# Initialize GCS client
gcs_client = GCSClient()


async def get_news_analysis(ticker: str, as_of: str = "latest") -> str:
    """Get news sentiment and catalyst analysis.

    Returns analysis from GammaRips' news_analyzer pipeline,
    identifying material catalysts and sentiment shifts.

    The 'score' field is a sentiment score from 0.0 (Very Bearish) to 1.0 (Very Bullish).
    - 0.0 - 0.2: Strong Sell / Negative
    - 0.2 - 0.4: Sell / Bearish
    - 0.4 - 0.6: Neutral
    - 0.6 - 0.8: Buy / Bullish
    - 0.8 - 1.0: Strong Buy / Positive

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL", "TSLA", "NVDA")
        as_of: Date for historical analysis in YYYY-MM-DD format, or "latest" for today (default: "latest")

    Returns:
        JSON string with news score, catalyst type, and analysis.

    Example:
        >>> result = await get_news_analysis("AAPL")
        >>> print(result)
        {
          "ticker": "AAPL",
          "as_of": "2026-01-04",
          "analysis": {
            "sentiment_score": 0.80,
            "catalyst_type": "Product Launch",
            "recent_headlines": [...],
            ...
          }
        }
    """
    try:
        # Validate ticker
        if not ticker or not ticker.strip():
            return json.dumps({"error": "Ticker is required"}, indent=2)

        # Query GCS
        result = await gcs_client.get_news_analysis(
            ticker=ticker.strip().upper(),
            as_of=as_of,
        )

        return json.dumps(result, indent=2)

    except Exception as e:
        logger.error(f"Error in get_news_analysis for {ticker}: {e}", exc_info=True)
        return json.dumps(
            {
                "error": f"Failed to fetch news analysis for {ticker}",
                "details": str(e),
            },
            indent=2,
        )
