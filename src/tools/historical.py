"""
Historical performance tool for GammaRips MCP.

Reads from `forward_paper_ledger` — the V5.3 paper-trader's realized bracket
trades (one pick per day, −60%/+80% bracket, 3-day hold). This is distinct
from `get_win_rate_summary` which reads `signal_performance` (the enriched-
signal outcome table, ALL signals, not just the daily V5.3 pick).

Chat agents should use this tool when a user asks "how has GammaRips' STRATEGY
done in the last 30 days?" — the realized strategy track record, not the
broader enriched-signals universe.
"""

from __future__ import annotations

import logging
import statistics
from typing import Any

from google.cloud import bigquery

from utils.safety import clamp, safe_error

logger = logging.getLogger(__name__)

try:
    client = bigquery.Client(project="profitscout-fida8")
except Exception as e:  # noqa: BLE001
    logger.error(f"Failed to initialize BigQuery client: {e}")
    client = None


def get_historical_performance(
    lookback_days: int = 30,
    direction: str | None = None,
    min_premium_score: int | None = None,
) -> dict[str, Any]:
    """
    Aggregate V5.3 paper-trader performance over a lookback window.

    READS FROM `forward_paper_ledger` — V5.3 realized trades only. Skips
    `INVALID_LIQUIDITY` and `SKIPPED` rows (terminal but uninformative). PIT-safe:
    only rows where exit_timestamp < today.

    Args:
        lookback_days: Lookback window in calendar days (default 30, clamped 1-365).
        direction: Optional filter — "bullish" or "bearish" (case-insensitive).
        min_premium_score: Optional integer floor on premium_score (0-6 typical).

    Returns:
        {
          "total_trades": int,
          "wins": int,                  # realized_return_pct > 0
          "losses": int,                # realized_return_pct <= 0
          "win_rate": float,            # 0.0-1.0
          "avg_return": float,          # mean of realized_return_pct
          "median_return": float,
          "best": float,                # max realized_return_pct
          "worst": float,               # min realized_return_pct
          "period": str,                # human-readable lookback summary
          "filters": {direction, min_premium_score, lookback_days},
        }
    """
    if not client:
        return {"error": "BigQuery client not initialized"}

    lookback_days = clamp(lookback_days, 1, 365, default=30)

    # Validate direction. We accept full or prefix forms — store-side values
    # are "BULLISH"/"BEARISH". Empty/None means no filter.
    dir_filter: str | None = None
    if direction:
        d = direction.strip().lower()
        if d.startswith("bull"):
            dir_filter = "BULLISH"
        elif d.startswith("bear"):
            dir_filter = "BEARISH"
        else:
            return {
                "error": f"direction must be 'bullish' or 'bearish' (got '{direction}')"
            }

    score_filter: int | None = None
    if min_premium_score is not None:
        score_filter = clamp(min_premium_score, 0, 10, default=0)

    try:
        query_parts = [
            """
            SELECT
                ticker, direction, premium_score, realized_return_pct, exit_reason,
                scan_date, entry_timestamp, exit_timestamp
            FROM `profitscout-fida8.profit_scout.forward_paper_ledger`
            WHERE exit_timestamp IS NOT NULL
              AND DATE(exit_timestamp) < CURRENT_DATE()
              AND entry_price IS NOT NULL
              AND exit_reason NOT IN ('INVALID_LIQUIDITY', 'SKIPPED')
              AND IFNULL(is_skipped, FALSE) = FALSE
              AND scan_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @lookback DAY)
            """
        ]
        params: list = [
            bigquery.ScalarQueryParameter("lookback", "INT64", lookback_days),
        ]
        if dir_filter:
            query_parts.append(" AND UPPER(direction) = @dir")
            params.append(bigquery.ScalarQueryParameter("dir", "STRING", dir_filter))
        if score_filter is not None:
            query_parts.append(" AND IFNULL(premium_score, 0) >= @min_score")
            params.append(bigquery.ScalarQueryParameter("min_score", "INT64", score_filter))

        query = "\n".join(query_parts) + "\n            ORDER BY exit_timestamp DESC\n            LIMIT 500"

        job = client.query(query, job_config=bigquery.QueryJobConfig(query_parameters=params))
        rows = list(job.result())

        if not rows:
            return {
                "total_trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0.0,
                "avg_return": 0.0,
                "median_return": 0.0,
                "best": 0.0,
                "worst": 0.0,
                "period": f"last {lookback_days} days (no trades matched filters)",
                "filters": {
                    "direction": dir_filter,
                    "min_premium_score": score_filter,
                    "lookback_days": lookback_days,
                },
            }

        returns = [r.realized_return_pct for r in rows if r.realized_return_pct is not None]
        wins = sum(1 for r in returns if r > 0)
        losses = sum(1 for r in returns if r <= 0)
        total = len(returns)

        avg = statistics.mean(returns) if returns else 0.0
        median = statistics.median(returns) if returns else 0.0
        best = max(returns) if returns else 0.0
        worst = min(returns) if returns else 0.0

        return {
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / total, 4) if total else 0.0,
            "avg_return": round(avg, 4),
            "median_return": round(median, 4),
            "best": round(best, 4),
            "worst": round(worst, 4),
            "period": f"last {lookback_days} days, V5.3 realized bracket trades",
            "filters": {
                "direction": dir_filter,
                "min_premium_score": score_filter,
                "lookback_days": lookback_days,
            },
        }

    except Exception as e:
        return {"error": safe_error(e, "get_historical_performance")}
