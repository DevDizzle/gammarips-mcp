"""
Historical performance tool for GammaRips MCP.

Reads from `forward_paper_ledger` — the engine's realized OPTION paper trades
(one tournament pick per day, simulated with real fills under the bracket
policy live at the time). This is distinct from `get_win_rate_summary`, which
reads `signal_performance` (UNDERLYING-stock direction outcomes for the broad
enriched pool — not option PnL).

Cohort discipline: rows carry `policy_version`, but since 2026-07-28 a cohort
reset is a DATE FILTER, not a truncation — disowned cohorts stay in the ledger
under the SAME label. So the live cohort is the PAIR (`V7_1_TILTED_GIGO`,
entry >= `LIVE_COHORT_START_DATE`), both from `utils.data`. Aggregates default
to that pair; mixing exit policies (or cohorts) in one aggregate produces
nonsense. Filtering on the label alone silently serves disowned rows — that
was the 2026-08-07 defect.
"""

from __future__ import annotations

import logging
import statistics
from typing import Any

from google.cloud import bigquery

from utils.data import BQ as client
from utils.data import (
    DISOWNED_COHORT_NOTE,
    FORWARD_PAPER_LEDGER,
    LIVE_COHORT_NOTE,
    LIVE_COHORT_START_DATE,
    LIVE_POLICY_VERSION,
)
from utils.safety import clamp, safe_error

logger = logging.getLogger(__name__)


def get_historical_performance(
    lookback_days: int = 30,
    direction: str | None = None,
    min_premium_score: int | None = None,
    policy_version: str | None = LIVE_POLICY_VERSION,
) -> dict[str, Any]:
    """
    Aggregate realized paper-trading performance (the engine's RECEIPTS) over
    a lookback window — one tournament pick per day, real-fill simulation.

    Defaults to the LIVE cohort (`V7_1_TILTED_GIGO` AND entry on/after
    2026-08-21: enter 10:00 ET day after scan, +40% target / -30% stop, flat
    15:45 ET same day). The cohort restarted 2026-08-21 (PRINT_FLOOR_MIN=25
    print-count liquidity floor; engine decision
    docs/DECISIONS/2026-08-20-score-floor-accepted-print-floor-25-shipped.md),
    so expect very small
    N — possibly zero; small-N aggregates are noise-heavy and must be quoted
    with their N. A zero here means "the cohort has not accrued closed trades
    yet", NOT "no track record", and the aggregates come back None rather than
    0.0. Pass policy_version="all" to reach every era — but "all" includes
    cohorts the engine has REPUDIATED (not merely different exit mechanics), so
    it is not a track record and must not be aggregated into one.

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
          "win_rate": float | None,     # 0.0-1.0; None when total_trades == 0
          "avg_return": float | None,   # mean of realized_return_pct (FRACTION)
          "median_return": float | None,
          "best": float | None,
          "worst": float | None,        # all None at N=0 — never 0.0
          "period": str,
          "cohort_start": str | None,   # set when the live cohort floor applied
          "filters": {direction, min_premium_score, lookback_days,
                      policy_version, cohort_start},
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
        cohort_floored = False
        # Normalize before BOTH the "all" test and the live-label test: a
        # caller passing "v7_1_tilted_gigo" would otherwise skip the date floor
        # AND then match zero rows (BigQuery string compare is case-sensitive),
        # i.e. a confusing empty result rather than the live cohort.
        pv = policy_version.strip() if policy_version else policy_version
        if pv and pv.casefold() == LIVE_POLICY_VERSION.casefold():
            pv = LIVE_POLICY_VERSION
        policy_version = pv
        if policy_version and policy_version.lower() != "all":
            query_parts.append(" AND policy_version = @policy_version")
            params.append(bigquery.ScalarQueryParameter("policy_version", "STRING", policy_version))
            # The label alone does NOT define the cohort — the ledger retains
            # disowned cohorts under the same label (date-filter resets since
            # 2026-07-28). Floor the LIVE cohort by its start date; an explicit
            # request for a historical label is left unfloored so callers can
            # still study prior eras.
            if policy_version == LIVE_POLICY_VERSION:
                query_parts.append(
                    " AND DATE(entry_timestamp, 'America/New_York') >= @cohort_start"
                )
                params.append(
                    bigquery.ScalarQueryParameter("cohort_start", "DATE", LIVE_COHORT_START_DATE)
                )
                cohort_floored = True

        query = (
            "\n".join(query_parts)
            + "\n            ORDER BY exit_timestamp DESC\n            LIMIT 500"
        )

        job = client.query(query, job_config=bigquery.QueryJobConfig(query_parameters=params))
        rows = list(job.result())

        cohort_label = policy_version or "all"
        cohort_start = LIVE_COHORT_START_DATE if cohort_floored else None

        def _cohort_note() -> str:
            """Every performance response carries a note, including empty ones.
            An empty result is still a performance claim about a paid product,
            so the compliance tail must never be conditional."""
            if cohort_floored:
                return LIVE_COHORT_NOTE
            return DISOWNED_COHORT_NOTE

        if not rows:
            # An empty live cohort is a MEANINGFUL state, not a failure and not
            # "no data": the cohort was reset and has not accrued closed trades
            # yet. Say so here, where the wrong conclusion would be drawn — a
            # bare zero reads as "the engine has no track record".
            if cohort_floored:
                period = (
                    f"last {lookback_days} days: the live cohort "
                    f"(start {LIVE_COHORT_START_DATE}) has no CLOSED trades yet. "
                    f"This is a cohort reset, not missing data."
                )
            else:
                period = f"last {lookback_days} days (no trades matched filters)"
            # NULL, not 0.0. A consumer extracts keys, not prose: `win_rate:
            # 0.0` on an empty cohort reads as "0% win rate" and `best: 0.0` as
            # "best trade was breakeven". Both are fabrications. This repo
            # already removed a bare `win_rate` key elsewhere for the weaker
            # version of this failure (a MISLABELED number); an INVENTED one is
            # worse. `total_trades: 0` is the only honest scalar here.
            return {
                "total_trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": None,
                "avg_return": None,
                "median_return": None,
                "best": None,
                "worst": None,
                "period": period,
                "cohort_start": cohort_start,
                "filters": {
                    "direction": dir_filter,
                    "min_premium_score": score_filter,
                    "lookback_days": lookback_days,
                    "policy_version": cohort_label,
                    "cohort_start": cohort_start,
                },
                "note": _cohort_note(),
            }

        returns = [r.realized_return_pct for r in rows if r.realized_return_pct is not None]
        wins = sum(1 for r in returns if r > 0)
        losses = sum(1 for r in returns if r <= 0)
        total = len(returns)

        # Same rule as the empty branch: with nothing to average, every stat is
        # NULL, never 0.0. Reachable independently of `rows` being empty — rows
        # can exist while every realized_return_pct is NULL — and that path does
        # NOT get the self-describing period string, so a fabricated zero here
        # would be entirely undisclosed.
        avg = statistics.mean(returns) if returns else None
        median = statistics.median(returns) if returns else None
        best = max(returns) if returns else None
        worst = min(returns) if returns else None

        return {
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / total, 4) if total else None,
            "avg_return": round(avg, 4) if avg is not None else None,
            "median_return": round(median, 4) if median is not None else None,
            "best": round(best, 4) if best is not None else None,
            "worst": round(worst, 4) if worst is not None else None,
            "period": (
                f"last {lookback_days} days, realized paper trades, "
                f"cohort={cohort_label}"
                + (f" since {LIVE_COHORT_START_DATE}" if cohort_floored else "")
            ),
            "cohort_start": cohort_start,
            "filters": {
                "direction": dir_filter,
                "min_premium_score": score_filter,
                "lookback_days": lookback_days,
                "policy_version": cohort_label,
                "cohort_start": cohort_start,
            },
            "note": (
                "Returns are FRACTIONS of entry premium. Realized rows only. " + _cohort_note()
            ),
        }

    except Exception as e:
        return {"error": safe_error(e, "get_historical_performance")}
