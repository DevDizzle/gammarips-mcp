"""
Tool: get_performance_tracker
Get signal performance metrics and track record
"""

import json
import logging

from data.bigquery_client import BigQueryClient

logger = logging.getLogger(__name__)

# Initialize BigQuery client (singleton pattern)
bq_client = BigQueryClient()


async def get_performance_tracker(
    status: str | None = None,
    ticker: str | None = None,
    option_type: str | None = None,
    min_gain: float | None = None,
    limit: int = 50,
) -> str:
    """Get performance metrics for tracked options signals.

    Returns historical performance data for signals that were identified by
    the GammaRips system, including entry price, current price, and P&L.

    **Note:** These are PAPER signals for demonstration purposes. No actual
    trades are executed. Performance is calculated from signal identification
    to current market price or expiration.

    Args:
        status: Filter by status - "Active", "Expired", "Delisted" (default: all)
        ticker: Filter by specific ticker symbol (e.g., "NVDA")
        option_type: Filter by "CALL" or "PUT" (default: both)
        min_gain: Minimum percent gain to filter (e.g., 10.0 for +10%)
        limit: Maximum results to return (default: 50, max: 100)

    Returns:
        JSON with performance summary and individual signal details including:
        - contract_symbol, ticker, option_type, strike_price
        - initial_price (entry), current_price, percent_gain
        - run_date (signal date), expiration_date, status
        - setup_quality_signal, stock_price_trend_signal

    Example:
        >>> result = await get_performance_tracker(status="Active", min_gain=5.0)
        >>> print(result)
        {
          "summary": {
            "total_signals": 45,
            "active": 12,
            "winners": 28,
            "losers": 17,
            "avg_gain_pct": 8.5,
            "win_rate_pct": 62.2
          },
          "signals": [...]
        }
    """
    try:
        # Validate inputs
        if limit > 100:
            limit = 100
        if limit < 1:
            limit = 1

        if status and status not in ["Active", "Expired", "Delisted"]:
            return json.dumps(
                {
                    "error": "Invalid status. Must be 'Active', 'Expired', or 'Delisted'.",
                    "valid_values": ["Active", "Expired", "Delisted"],
                },
                indent=2,
            )

        if option_type and option_type.upper() not in ["CALL", "PUT"]:
            return json.dumps(
                {
                    "error": "Invalid option_type. Must be 'CALL' or 'PUT'.",
                    "valid_values": ["CALL", "PUT"],
                },
                indent=2,
            )

        # Query BigQuery
        result = await bq_client.get_performance_tracker(
            status=status,
            ticker=ticker.upper() if ticker else None,
            option_type=option_type.upper() if option_type else None,
            min_gain=min_gain,
            limit=limit,
        )

        return json.dumps(result, indent=2)

    except Exception as e:
        logger.error(f"Error in get_performance_tracker: {e}", exc_info=True)
        return json.dumps(
            {
                "error": "Failed to fetch performance tracker",
                "details": str(e),
            },
            indent=2,
        )


async def get_performance_summary() -> str:
    """Get aggregate performance statistics for all tracked signals.

    Returns high-level KPIs including win rate, average return, and
    performance breakdown by signal quality and option type.

    Returns:
        JSON with aggregate statistics:
        - Total signals tracked
        - Win rate (% of signals with positive return)
        - Average gain/loss percentage
        - Breakdown by status (Active/Expired/Delisted)
        - Breakdown by quality signal (High/Medium/Low)
        - Best and worst performing signals

    Example:
        >>> result = await get_performance_summary()
        >>> print(result)
        {
          "as_of": "2026-02-01",
          "total_signals": 156,
          "win_rate_pct": 58.3,
          "avg_return_pct": 12.4,
          "by_quality": {
            "High": {"count": 45, "win_rate": 71.1, "avg_return": 18.2},
            ...
          }
        }
    """
    try:
        result = await bq_client.get_performance_summary()
        return json.dumps(result, indent=2)

    except Exception as e:
        logger.error(f"Error in get_performance_summary: {e}", exc_info=True)
        return json.dumps(
            {
                "error": "Failed to fetch performance summary",
                "details": str(e),
            },
            indent=2,
        )
