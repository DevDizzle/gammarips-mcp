"""
Tool: get_stock_analysis
Get comprehensive analysis for a specific stock
"""

import json
import logging

from data.bigquery_client import BigQueryClient
from data.gcs_client import GCSClient

logger = logging.getLogger(__name__)

# Initialize clients
bq_client = BigQueryClient()
gcs_client = GCSClient()


async def get_stock_analysis(
    ticker: str,
    include_sections: list[str] | None = None,
    as_of: str = "latest",
) -> str:
    """Get comprehensive stock analysis including fundamentals, financials, business, technicals, news, and reports.

    Combines data from multiple GammaRips analysis pipelines to provide
    a complete picture of the stock's current state and outlook.

    Available Sections:
    - "business": Business summary and profile.
    - "fundamentals": Key valuation metrics (P/E, Market Cap).
    - "financials": Deep dive financial health (Revenue, Debt, Cash Flow).
    - "technicals": Technical analysis (Trend, RSI, Patterns).
    - "news": News sentiment and catalysts.

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL", "TSLA", "NVDA")
        include_sections: List of sections to include. If not specified, all sections are included.
        as_of: Date for historical analysis in YYYY-MM-DD format, or "latest" for today (default: "latest")

    Returns:
        JSON string with requested analysis sections.
    """
    try:
        # Validate ticker
        if not ticker or not ticker.strip():
            return json.dumps({"error": "Ticker is required"}, indent=2)

        ticker = ticker.strip().upper()

        # Default to all sections if not specified
        valid_sections = ["business", "fundamentals", "financials", "technicals", "news"]

        if not include_sections:
            include_sections = valid_sections

        # Validate sections
        for section in include_sections:
            if section not in valid_sections:
                return json.dumps(
                    {
                        "error": f"Invalid section: {section}",
                        "valid_sections": valid_sections,
                    },
                    indent=2,
                )

        # Build the response
        result = {
            "ticker": ticker,
            "as_of": as_of,
        }

        # Fetch requested sections
        if "business" in include_sections:
            data = await gcs_client.get_business_summary(ticker, as_of)
            result["business"] = data.get("data")

        if "fundamentals" in include_sections:
            data = await gcs_client.get_fundamental_analysis(ticker, as_of)
            result["fundamentals"] = data.get("data")

        if "financials" in include_sections:
            data = await gcs_client.get_financial_analysis(ticker, as_of)
            result["financials"] = data.get("data")

        if "technicals" in include_sections:
            tech_data = await gcs_client.get_technical_analysis(ticker, as_of)
            result["technicals"] = tech_data.get("analysis")

        if "news" in include_sections:
            news_data = await gcs_client.get_news_analysis(ticker, as_of)
            result["news"] = news_data.get("analysis")

        return json.dumps(result, indent=2)

    except Exception as e:
        logger.error(f"Error in get_stock_analysis for {ticker}: {e}", exc_info=True)
        return json.dumps(
            {
                "error": f"Failed to fetch stock analysis for {ticker}",
                "details": str(e),
            },
            indent=2,
        )
