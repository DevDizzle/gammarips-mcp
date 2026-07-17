"""
Historical performance tool for GammaRips MCP.

Reads from `forward_paper_ledger` — the engine's realized OPTION paper trades
(one tournament pick per day, simulated with real fills under the bracket
policy live at the time). This is distinct from `get_win_rate_summary`, which
reads `signal_performance` (UNDERLYING-stock direction outcomes for the broad
enriched pool — not option PnL).

Cohort discipline: the ledger is truncated at each policy cutover and rows
carry `policy_version`. Aggregates default to the LIVE cohort only
(`V7_1_TILTED_GIGO`, since 2026-06-26) — mixing exit policies in one
aggregate produces nonsense.
"""

from __future__ import annotations

import logging
import statistics
from typing import Any

from google.cloud import bigquery

from utils.data import BQ as client
from utils.data import FORWARD_PAPER_LEDGER
from utils.safety import clamp, safe_error

logger = logging.getLogger(__name__)

LIVE_POLICY_VERSION = "V7_1_TILTED_GIGO"


def get_historical_performance(
    lookback_days: int = 30,
    direction: str | None = None,
    min_premium_score: int | None = None,
    policy_version: str | None = LIVE_POLICY_VERSION,
) -> dict[str, Any]:
    """
    Aggregate realized paper-trading performance (the engine's RECEIPTS) over
    a lookback window — one tournament pick per day, real-fill simulation.

    Defaults to the LIVE cohort (`V7_1_TILTED_GIGO`, since 2026-06-26: enter
    10:00 ET day after scan, +40% target / -30% stop, flat 15:45 ET same day).
    The cohort is young — expect small N; small-N aggregates are noise-heavy
    and should be quoted with their N. Pass policy_version="all" to see all
    eras (different exit mechanics — comparison is on you).

    Realized-only: rows appear after exit, never same-day. All returns are
    FRACTIONS of entry premium (0.40 = +40%). Paper-traded. Not investment
    advice.

    Args:
        lookback_days: Lookback window in calendar days (default 30, clamped 1-365).
        direction: Optional filter — "bullish" or "bearish" (case-insensitive).
        min_premium_score: Optional integer floor on premium_score (0-6 typical).
        policy_version: Cohort filter (default = live cohort; "all" for every era).

    Returns:
        {
          "total_trades": int,
          "wins": int,                  # realized_return_pct > 0
          "losses": int,                # realized_return_pct <= 0
          "win_rate": float,            # 0.0-1.0
          "avg_return": float,          # mean of realized_return_pct (FRACTION)
          "median_return": float,
          "best": float,
          "worst": float,
          "period": str,
          "filters": {direction, min_premium_score, lookback_days, policy_version},
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
            return {"error": f"direction must be 'bullish' or 'bearish' (got '{direction}')"}

    score_filter: int | None = None
    if min_premium_score is not None:
        score_filter = clamp(min_premium_score, 0, 10, default=0)

    try:
        query_parts = [
            """
            SELECT
                ticker, direction, premium_score, realized_return_pct, exit_reason,
                scan_date, entry_timestamp, exit_timestamp, policy_version
            FROM """
            + FORWARD_PAPER_LEDGER
            + """
            WHERE exit_timestamp IS NOT NULL
              AND DATE(exit_timestamp, 'America/New_York') < CURRENT_DATE('America/New_York')
              AND entry_price IS NOT NULL
              AND exit_reason NOT IN ('INVALID_LIQUIDITY', 'SKIPPED')
              AND IFNULL(is_skipped, FALSE) = FALSE
              AND scan_date >= DATE_SUB(CURRENT_DATE('America/New_York'), INTERVAL @lookback DAY)
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
        if policy_version and policy_version.lower() != "all":
            query_parts.append(" AND policy_version = @policy_version")
            params.append(bigquery.ScalarQueryParameter("policy_version", "STRING", policy_version))

        query = (
            "\n".join(query_parts)
            + "\n            ORDER BY exit_timestamp DESC\n            LIMIT 500"
        )

        job = client.query(query, job_config=bigquery.QueryJobConfig(query_parameters=params))
        rows = list(job.result())

        cohort_label = policy_version or "all"
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
                    "policy_version": cohort_label,
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
            "period": f"last {lookback_days} days, realized paper trades, cohort={cohort_label}",
            "filters": {
                "direction": dir_filter,
                "min_premium_score": score_filter,
                "lookback_days": lookback_days,
                "policy_version": cohort_label,
            },
            "note": (
                "Returns are FRACTIONS of entry premium. Realized rows only. "
                "Paper-traded. Not investment advice."
            ),
        }

    except Exception as e:
        return {"error": safe_error(e, "get_historical_performance")}
