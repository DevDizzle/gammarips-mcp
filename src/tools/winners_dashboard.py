"""
Tool: get_winners_dashboard
Get today's top-ranked options signals across all tickers
"""

import json
import logging

from data.bigquery_client import BigQueryClient

logger = logging.getLogger(__name__)

# Initialize BigQuery client (singleton pattern)
bq_client = BigQueryClient()


async def get_winners_dashboard(
    limit: int = 10,
    option_type: str | None = None,
    min_quality: str | None = None,
) -> str:
    """Get today's top-ranked options signals.

    Returns the highest-conviction options setups for the current trading day,
    ranked by setup quality, trend alignment, and volatility favorability.

    **Note:** This tool provides SIGNALS (Trend, Quality). For specific contract details
    (Gamma, Delta, Greeks) or to find "High Gamma" options, use `analyze_market_structure`.

    Args:
        limit: Maximum number of signals to return (default: 10, max: 50)
        option_type: Filter by CALL or PUT (default: both)
        min_quality: Minimum setup quality - "High", "Medium", or "Low" (default: all)

    Returns:
        JSON string with top signals including ticker, option_type, strike, expiration,
        current_price, setup_quality_signal, stock_price_trend_signal,
        volatility_comparison_signal, breakeven_price, expected_move, weighted_score, and analysis_summary.

    Example:
        >>> result = await get_winners_dashboard(limit=5, option_type="CALL", min_quality="High")
        >>> print(result)
        {
          "as_of": "2026-01-04",
          "count": 5,
          "signals": [
            {
              "ticker": "NVDA",
              "option_type": "CALL",
              "strike": 145.0,
              "expiration": "2026-02-21",
              "current_price": 140.25,
              "setup_quality_signal": "High",
              ...
            }
          ]
        }
    """
    try:
        # Validate inputs
        if limit > 50:
            limit = 50
        if limit < 1:
            limit = 1

        if option_type and option_type.upper() not in ["CALL", "PUT"]:
            return json.dumps(
                {
                    "error": "Invalid option_type. Must be 'CALL' or 'PUT'.",
                    "valid_values": ["CALL", "PUT"],
                },
                indent=2,
            )

        if min_quality and min_quality not in ["High", "Medium", "Low"]:
            return json.dumps(
                {
                    "error": "Invalid min_quality. Must be 'High', 'Medium', or 'Low'.",
                    "valid_values": ["High", "Medium", "Low"],
                },
                indent=2,
            )

        # Query BigQuery
        result = await bq_client.get_winners_dashboard(
            limit=limit,
            option_type=option_type.upper() if option_type else None,
            min_quality=min_quality,
        )

        return json.dumps(result, indent=2)

    except Exception as e:
        logger.error(f"Error in get_winners_dashboard: {e}", exc_info=True)
        return json.dumps(
            {
                "error": "Failed to fetch winners dashboard",
                "details": str(e),
            },
            indent=2,
        )
