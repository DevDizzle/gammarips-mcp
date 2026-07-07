"""
Research-substrate tools for GammaRips MCP (V3).

These tools expose the leakage-safe research substrate behind the engine:

  * `enriched_features_v1` — the ALLOWLIST view of point-in-time features
    (identity + feature + cohort-meta columns only; every outcome/label/
    telemetry column is physically excluded). Features are served ONLY
    through this view.
  * `enriched_option_outcomes` — the daily full-pool bracket-replay label
    table (~50 contracts/day). Touched ONLY for label / opportunity-surface
    columns, joined back to view-served features ("label joins only").

Leakage rules baked into every query here:
  - A FEATURE is known as-of <= scan_date. Realized data (labels, the
    opportunity surface) is served only for CLOSED windows.
  - Same-day and 3-day labels are distinct horizons and are never pooled.
  - Whole-pool composites under a fixed exit are NEGATIVE — these tools are
    a research surface, not a strategy return. Aggregation tools carry an
    explicit disclaimer.

All returns in the substrate are FRACTIONS (0.40 = +40%). Tool parameters
that accept a bracket use human-friendly PERCENT units and say so.
"""

from __future__ import annotations

import logging
import math
from datetime import timedelta as _timedelta
from typing import Any
from zoneinfo import ZoneInfo

from google.cloud import bigquery

from utils.safety import MAX_RESPONSE_ROWS, clamp, safe_error

logger = logging.getLogger(__name__)

_ET_TZ = ZoneInfo("America/New_York")
_ONE_DAY = _timedelta(days=1)

try:
    client = bigquery.Client(project="profitscout-fida8")
except Exception as e:  # noqa: BLE001
    logger.error(f"Failed to initialize BigQuery client: {e}")
    client = None

_FEATURES_VIEW = "`profitscout-fida8.profit_scout.enriched_features_v1`"
_OUTCOMES_TABLE = "`profitscout-fida8.profit_scout.enriched_option_outcomes`"

# Same-day GIGO bracket (V7.1 live policy) and the legacy 3-day companion
# bracket, in FRACTION units as stored in the label-semantics columns.
_EXACT_LABEL_RULES = {
    "same_day": {"target": 0.40, "stop": 0.30, "label_col": "realized_return_pct"},
    "3d": {"target": 0.80, "stop": 0.60, "label_col": "realized_return_pct_3d"},
}

_COMPOSITE_DISCLAIMER = (
    "Whole-pool composites under any FIXED exit rule are negative — the pool "
    "surfaces opportunity (excursion potential), not a packaged return. Use "
    "these aggregates to study how outcomes distribute across features and "
    "exits, not as a strategy track record. Paper-traded research data. "
    "Not investment advice."
)


def _pick_flag_guard(prefix: str = "") -> str:
    """SELECT ... REPLACE clause that NULLs the cohort pick flags until the
    entry day is strictly past (ET). The engine's label pass normally lags a
    day anyway, but that lag is cron scheduling, not physics — this makes the
    pick-privacy guarantee structural inside the MCP: the operator's current
    selection can never be read off the substrate, regardless of when the
    upstream labeler runs."""
    p = prefix
    return (
        "REPLACE ("
        f"IF({p}entry_day < CURRENT_DATE('America/New_York'), "
        f"{p}was_tournament_pick, NULL) AS was_tournament_pick, "
        f"IF({p}entry_day < CURRENT_DATE('America/New_York'), "
        f"{p}was_topscore_pick, NULL) AS was_topscore_pick)"
    )


def _serialize(r: dict[str, Any]) -> dict[str, Any]:
    for k, v in list(r.items()):
        if hasattr(v, "isoformat"):
            r[k] = v.isoformat()
    return r


def _latest_scan_date(sql_from: str, where: str = "TRUE") -> str | None:
    q = f"SELECT CAST(MAX(scan_date) AS STRING) AS d FROM {sql_from} WHERE {where}"
    for row in client.query(q).result():
        return row.d
    return None


def get_pool_features(
    scan_date: str | None = None,
    ticker: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """
    Point-in-time FEATURE VECTORS for the labeled candidate pool, served from
    the leakage-safe allowlist view `enriched_features_v1` (identity + features
    + cohort metadata only — no outcome, label, or telemetry column can appear
    here by construction).

    This is the quantitative substrate for research and for joining against
    `query_outcomes` / `get_opportunity_surface`. NOTE: the labeled substrate
    lags the live pool by ~1-2 trading days (rows appear once the same-day
    replay has run). For TODAY'S live pool with narrative enrichment, use
    `get_enriched_signals` instead.

    Every feature is known as-of <= scan_date (the selection point). Caveats:
    `recommended_oi` / `recommended_volume` (and derived `volume_oi_ratio`,
    `moneyness_pct`) are session-frozen snapshots; `recommended_spread_pct` is
    permanently NULL on the current data plan.

    Args:
        scan_date: YYYY-MM-DD. Defaults to the most recent labeled scan date.
        ticker: Optional ticker filter.
        limit: Max rows (default 50, clamped 1-100).

    Returns:
        {scan_date, row_count, rows: [feature vectors...]}
    """
    if not client:
        return {"error": "BigQuery client not initialized"}

    limit = clamp(limit, 1, 100, default=50)

    try:
        if not scan_date:
            scan_date = _latest_scan_date(_FEATURES_VIEW)
        if not scan_date:
            return {"error": "No data found in the features view"}

        query = f"""
            SELECT * {_pick_flag_guard()}
            FROM {_FEATURES_VIEW}
            WHERE scan_date = @scan_date
        """
        params = [bigquery.ScalarQueryParameter("scan_date", "DATE", scan_date)]
        if ticker:
            query += " AND ticker = @ticker"
            params.append(bigquery.ScalarQueryParameter("ticker", "STRING", ticker))
        query += " ORDER BY overnight_score DESC, ticker LIMIT @limit"
        params.append(bigquery.ScalarQueryParameter("limit", "INTEGER", limit))

        job_config = bigquery.QueryJobConfig(query_parameters=params)
        rows = [_serialize(dict(r)) for r in client.query(query, job_config=job_config).result()]
        if not rows:
            latest = _latest_scan_date(_FEATURES_VIEW)
            return {
                "scan_date": scan_date,
                "row_count": 0,
                "rows": [],
                "latest_labeled_scan_date": latest,
                "note": (
                    "No labeled feature rows for this scan_date/filter. The "
                    "labeled substrate lags the live pool by ~1-2 trading days — "
                    f"latest labeled scan_date is {latest}. For today's live pool "
                    "use get_enriched_signals."
                ),
            }
        return {"scan_date": scan_date, "row_count": len(rows), "rows": rows}

    except Exception as e:
        return {"error": safe_error(e, "get_pool_features")}


def get_opportunity_surface(
    scan_date: str | None = None,
    ticker: str | None = None,
    days: int = 30,
    include_open: bool = False,
) -> dict[str, Any]:
    """
    The OPPORTUNITY SURFACE — per-contract realized excursions of the option
    premium over a fixed multi-day window with NO exit rule applied. This is
    "profit potential with the exit left as a free variable": your agent
    derives any entry/exit policy offline from these extremes.

    Per contract: `opp_peak_return` (max favorable excursion / MFE) and
    `opp_trough_return` (max adverse excursion / MAE) as FRACTIONS of the
    10:00 ET entry cost basis (0.40 = +40%), `opp_minutes_to_peak/trough`
    (minutes from entry to each extreme), `opp_window_days` (trading days in
    the window, entry day included), and `opp_status`.

    This is NOT a tradeable label and NOT a feature — it is realized excursion
    over a closed window. Only rows whose window has fully closed are returned
    by default (`opp_status='OK'`).

    Args:
        scan_date: YYYY-MM-DD — return just that scan date's pool.
        ticker: Optional ticker filter (across the lookback if no scan_date).
        days: Lookback window in days when scan_date is not given
            (default 30, clamped 1-120).
        include_open: Include rows whose excursion window has not closed yet
            (opp_status != 'OK'; their MFE/MAE columns are NULL/partial).

    Returns:
        {row_count, rows: [...], meta: {statuses_included, note}}
    """
    if not client:
        return {"error": "BigQuery client not initialized"}

    days = clamp(days, 1, 120, default=30)

    try:
        query = f"""
            SELECT
                scan_date, entry_day, ticker, direction,
                recommended_contract, recommended_strike, recommended_expiration,
                recommended_dte,
                opp_entry_timestamp, opp_entry_price,
                opp_peak_return, opp_trough_return,
                opp_minutes_to_peak, opp_minutes_to_trough,
                opp_bar_count, opp_window_days, opp_status, opp_sim_version
            FROM {_OUTCOMES_TABLE}
            WHERE TRUE
        """
        params: list = []
        if scan_date:
            query += " AND scan_date = @scan_date"
            params.append(bigquery.ScalarQueryParameter("scan_date", "DATE", scan_date))
        else:
            query += (
                " AND scan_date >= DATE_SUB(CURRENT_DATE('America/New_York'), INTERVAL @days DAY)"
            )
            params.append(bigquery.ScalarQueryParameter("days", "INTEGER", days))
        if ticker:
            query += " AND ticker = @ticker"
            params.append(bigquery.ScalarQueryParameter("ticker", "STRING", ticker))
        if not include_open:
            query += " AND opp_status = 'OK'"

        query += f" ORDER BY scan_date DESC, opp_peak_return DESC LIMIT {MAX_RESPONSE_ROWS}"

        job_config = bigquery.QueryJobConfig(query_parameters=params)
        rows = [_serialize(dict(r)) for r in client.query(query, job_config=job_config).result()]
        return {
            "row_count": len(rows),
            "rows": rows,
            "meta": {
                "statuses_included": "all" if include_open else "OK (closed windows only)",
                "note": (
                    "Returns are FRACTIONS of the 10:00 ET entry cost basis "
                    "(entry-bar close + entry slippage; no exit slippage — this is "
                    "the raw achievable path). Realized excursion data: never use "
                    "as a selection feature for the same scan_date."
                ),
            },
        }

    except Exception as e:
        return {"error": safe_error(e, "get_opportunity_surface")}


_LABEL_COLS = {
    "same_day": """
                o.entry_timestamp, o.entry_price, o.exit_timestamp, o.exit_reason,
                o.realized_return_pct, o.exit_slippage, o.illiquid_exit,
                o.late_fill_minutes,
                o.label_sim_version, o.label_hold_days, o.label_stop_pct, o.label_target_pct""",
    "3d": """
                o.entry_price_3d, o.exit_timestamp_3d, o.exit_day_3d, o.exit_reason_3d,
                o.realized_return_pct_3d, o.peak_premium_3d,
                o.label_3d_sim_version, o.label_3d_hold_days, o.label_3d_stop_pct,
                o.label_3d_target_pct""",
}


def query_outcomes(
    horizon: str = "same_day",
    scan_date_from: str | None = None,
    scan_date_to: str | None = None,
    ticker: str | None = None,
    delta_min: float | None = None,
    delta_max: float | None = None,
    min_overnight_score: int | None = None,
    exit_reason: str | None = None,
    limit: int = 100,
    aggregate_only: bool = False,
) -> dict[str, Any]:
    """
    Row-level REALIZED LABELS for the full candidate pool, joined to their
    point-in-time feature vectors. Ask questions like "how did pool contracts
    with |delta| 0.20-0.46 behave under the same-day bracket?"

    Two distinct label horizons — never pooled together:
      * `same_day`: the live V7.1 GIGO bracket (enter 10:00 ET day after scan,
        +40% target / -30% stop, flat 15:45 ET same day). Label =
        `realized_return_pct` (FRACTION).
      * `3d`: the legacy 3-trading-day companion bracket (+80% / -60%,
        exit 15:50 ET day 3). Label = `realized_return_pct_3d`.

    Features come from the leakage-safe `enriched_features_v1` allowlist view;
    label columns are joined from the outcome table (label-join pattern). Rows
    with NULL labels and (same-day) `illiquid_exit=TRUE` rows are EXCLUDED by
    default — exclusion counts are reported in `meta` because the illiquid
    tail (~28% of the pool) is non-random and must not be silently hidden.

    Args:
        horizon: "same_day" or "3d".
        scan_date_from / scan_date_to: YYYY-MM-DD range bounds (inclusive).
        ticker: Optional ticker filter.
        delta_min / delta_max: Bounds on |recommended_delta| (0-1).
        min_overnight_score: Floor on overnight_score (1-10).
        exit_reason: Filter (TARGET | STOP | TIMEOUT | ...) on the chosen horizon.
        limit: Max rows (default 100, clamped 1-200).
        aggregate_only: True = skip row-level output and return summary stats
            (n, win_rate, avg/median/p25/p75, avg MFE/MAE) over the filtered
            set — rows are verbose; use this when you only need the shape.

    Returns:
        {horizon, row_count, rows: [...features + labels...],
         meta: {excluded_null_label, excluded_illiquid, pool_rows_in_window, note}}
        or, with aggregate_only: {horizon, aggregate: {...}, meta: {...}}.
    """
    if not client:
        return {"error": "BigQuery client not initialized"}

    if horizon not in _LABEL_COLS:
        return {"error": "horizon must be 'same_day' or '3d'"}
    limit = clamp(limit, 1, MAX_RESPONSE_ROWS, default=100)
    label_col = "o.realized_return_pct" if horizon == "same_day" else "o.realized_return_pct_3d"

    try:
        filters = ["TRUE"]
        params: list = []
        if scan_date_from:
            filters.append("f.scan_date >= @dfrom")
            params.append(bigquery.ScalarQueryParameter("dfrom", "DATE", scan_date_from))
        if scan_date_to:
            filters.append("f.scan_date <= @dto")
            params.append(bigquery.ScalarQueryParameter("dto", "DATE", scan_date_to))
        if ticker:
            filters.append("f.ticker = @ticker")
            params.append(bigquery.ScalarQueryParameter("ticker", "STRING", ticker))
        if delta_min is not None:
            filters.append("ABS(f.recommended_delta) >= @dmin")
            params.append(bigquery.ScalarQueryParameter("dmin", "FLOAT64", float(delta_min)))
        if delta_max is not None:
            filters.append("ABS(f.recommended_delta) <= @dmax")
            params.append(bigquery.ScalarQueryParameter("dmax", "FLOAT64", float(delta_max)))
        if min_overnight_score is not None:
            filters.append("f.overnight_score >= @minscore")
            params.append(
                bigquery.ScalarQueryParameter(
                    "minscore", "INTEGER", clamp(min_overnight_score, 1, 10, default=1)
                )
            )
        exit_col = "o.exit_reason" if horizon == "same_day" else "o.exit_reason_3d"
        if exit_reason:
            filters.append(f"UPPER({exit_col}) = UPPER(@exit_reason)")
            params.append(bigquery.ScalarQueryParameter("exit_reason", "STRING", exit_reason))

        where = " AND ".join(filters)
        illiq = "IFNULL(o.illiquid_exit, FALSE)" if horizon == "same_day" else "FALSE"

        if aggregate_only:
            agg_query = f"""
                SELECT
                    COUNT(*) AS n,
                    ROUND(SAFE_DIVIDE(COUNTIF({label_col} > 0), COUNT(*)), 4) AS win_rate,
                    ROUND(AVG({label_col}), 4) AS avg_return,
                    ROUND(APPROX_QUANTILES({label_col}, 100)[OFFSET(50)], 4) AS median_return,
                    ROUND(APPROX_QUANTILES({label_col}, 100)[OFFSET(25)], 4) AS p25_return,
                    ROUND(APPROX_QUANTILES({label_col}, 100)[OFFSET(75)], 4) AS p75_return,
                    ROUND(AVG(IF(o.opp_status = 'OK', o.opp_peak_return, NULL)), 4) AS avg_mfe,
                    ROUND(AVG(IF(o.opp_status = 'OK', o.opp_trough_return, NULL)), 4) AS avg_mae
                FROM {_FEATURES_VIEW} f
                JOIN {_OUTCOMES_TABLE} o
                  USING (scan_date, ticker, recommended_contract)
                WHERE {where}
                  AND {label_col} IS NOT NULL
                  AND NOT {illiq}
            """
            agg_row = next(
                iter(
                    client.query(
                        agg_query, job_config=bigquery.QueryJobConfig(query_parameters=params)
                    ).result()
                ),
                None,
            )
            meta_row = next(
                iter(
                    client.query(
                        f"""
                        SELECT
                            COUNT(*) AS pool_rows_in_window,
                            COUNTIF({label_col} IS NULL) AS excluded_null_label,
                            COUNTIF({label_col} IS NOT NULL AND {illiq}) AS excluded_illiquid
                        FROM {_FEATURES_VIEW} f
                        JOIN {_OUTCOMES_TABLE} o
                          USING (scan_date, ticker, recommended_contract)
                        WHERE {where}
                        """,
                        job_config=bigquery.QueryJobConfig(query_parameters=params),
                    ).result()
                ),
                None,
            )
            return {
                "horizon": horizon,
                "aggregate": _serialize(dict(agg_row)) if agg_row else {},
                "meta": {
                    "pool_rows_in_window": meta_row.pool_rows_in_window if meta_row else None,
                    "excluded_null_label": meta_row.excluded_null_label if meta_row else None,
                    "excluded_illiquid": meta_row.excluded_illiquid if meta_row else None,
                    "note": (
                        "Aggregate over the filtered set; FRACTION units. " + _COMPOSITE_DISCLAIMER
                    ),
                },
            }

        query = f"""
            SELECT
                f.* {_pick_flag_guard("f.")},
                {_LABEL_COLS[horizon]},
                IF(o.opp_status = 'OK', o.opp_peak_return, NULL) AS opp_peak_return,
                IF(o.opp_status = 'OK', o.opp_trough_return, NULL) AS opp_trough_return,
                o.opp_status
            FROM {_FEATURES_VIEW} f
            JOIN {_OUTCOMES_TABLE} o
              USING (scan_date, ticker, recommended_contract)
            WHERE {where}
              AND {label_col} IS NOT NULL
              AND NOT {illiq}
            ORDER BY f.scan_date DESC, {label_col} DESC
            LIMIT @limit
        """
        meta_query = f"""
            SELECT
                COUNT(*) AS pool_rows_in_window,
                COUNTIF({label_col} IS NULL) AS excluded_null_label,
                COUNTIF({label_col} IS NOT NULL AND {illiq}) AS excluded_illiquid
            FROM {_FEATURES_VIEW} f
            JOIN {_OUTCOMES_TABLE} o
              USING (scan_date, ticker, recommended_contract)
            WHERE {where}
        """

        row_params = params + [bigquery.ScalarQueryParameter("limit", "INTEGER", limit)]
        rows = [
            _serialize(dict(r))
            for r in client.query(
                query, job_config=bigquery.QueryJobConfig(query_parameters=row_params)
            ).result()
        ]
        meta_row = next(
            iter(
                client.query(
                    meta_query, job_config=bigquery.QueryJobConfig(query_parameters=params)
                ).result()
            ),
            None,
        )

        return {
            "horizon": horizon,
            "row_count": len(rows),
            "rows": rows,
            "meta": {
                "pool_rows_in_window": meta_row.pool_rows_in_window if meta_row else None,
                "excluded_null_label": meta_row.excluded_null_label if meta_row else None,
                "excluded_illiquid": meta_row.excluded_illiquid if meta_row else None,
                "note": (
                    "Labels are FRACTIONS (0.40 = +40%). The excluded illiquid/"
                    "unlabeled tail is non-random — factor it into any conclusion. "
                    + _COMPOSITE_DISCLAIMER
                ),
            },
        }

    except Exception as e:
        return {"error": safe_error(e, "query_outcomes")}


_GROUP_EXPRS = {
    "none": "'ALL'",
    "delta_bucket": (
        "CASE WHEN f.recommended_delta IS NULL THEN 'unknown' "
        "WHEN ABS(f.recommended_delta) < 0.20 THEN 'lt_0.20' "
        "WHEN ABS(f.recommended_delta) <= 0.46 THEN '0.20_to_0.46' "
        "ELSE 'gt_0.46' END"
    ),
    "overnight_score": "CAST(f.overnight_score AS STRING)",
    "premium_score": "CAST(f.premium_score AS STRING)",
    "exit_reason": None,  # resolved per horizon below
    "day_of_week": "FORMAT_DATE('%A', f.entry_day)",
    # moneyness_pct is a FRACTION (0.05 = 5% OTM; negative = ITM at scan) and a
    # session-frozen scan-time snapshot.
    "moneyness_bucket": (
        "CASE WHEN f.moneyness_pct IS NULL THEN 'unknown' "
        "WHEN f.moneyness_pct <= 0 THEN 'itm_at_scan' "
        "WHEN f.moneyness_pct < 0.05 THEN 'otm_0_5pct' "
        "WHEN f.moneyness_pct < 0.10 THEN 'otm_5_10pct' "
        "WHEN f.moneyness_pct < 0.15 THEN 'otm_10_15pct' "
        "ELSE 'otm_15pct_plus' END"
    ),
}


def get_outcome_summary(
    horizon: str = "same_day",
    group_by: str = "none",
    scan_date_from: str | None = None,
    scan_date_to: str | None = None,
) -> dict[str, Any]:
    """
    Aggregate realized-label statistics over the full labeled pool, optionally
    grouped by a whitelisted feature dimension. The exploration companion to
    `query_outcomes` — use it to see how outcomes distribute before pulling
    row-level data.

    Per group: n, win_rate (label > 0), avg/median/p25/p75 of the label,
    avg MFE (`opp_peak_return`) and avg MAE (`opp_trough_return`). Labels and
    excursions are FRACTIONS (0.40 = +40%).

    IMPORTANT: the whole-pool composite under any fixed exit is NEGATIVE by
    design of the problem — the pool sells opportunity, not a return. This
    tool exists to study CONDITIONAL structure (which feature slices behave
    differently), not to compute a strategy track record.

    Args:
        horizon: "same_day" (live V7.1 GIGO bracket) or "3d" (legacy +80/-60).
        group_by: one of none | delta_bucket | overnight_score | premium_score
            | exit_reason | day_of_week | moneyness_bucket. Strict whitelist.
        scan_date_from / scan_date_to: YYYY-MM-DD range bounds (inclusive).

    Returns:
        {horizon, group_by, groups: [...], meta: {exclusions, disclaimer}}
    """
    if not client:
        return {"error": "BigQuery client not initialized"}

    if horizon not in _LABEL_COLS:
        return {"error": "horizon must be 'same_day' or '3d'"}
    if group_by not in _GROUP_EXPRS:
        return {"error": f"group_by must be one of {sorted(_GROUP_EXPRS)}"}

    label_col = "o.realized_return_pct" if horizon == "same_day" else "o.realized_return_pct_3d"
    group_expr = _GROUP_EXPRS[group_by]
    if group_by == "exit_reason":
        group_expr = "o.exit_reason" if horizon == "same_day" else "o.exit_reason_3d"
    illiq = "IFNULL(o.illiquid_exit, FALSE)" if horizon == "same_day" else "FALSE"

    try:
        filters = ["TRUE"]
        params: list = []
        if scan_date_from:
            filters.append("f.scan_date >= @dfrom")
            params.append(bigquery.ScalarQueryParameter("dfrom", "DATE", scan_date_from))
        if scan_date_to:
            filters.append("f.scan_date <= @dto")
            params.append(bigquery.ScalarQueryParameter("dto", "DATE", scan_date_to))
        where = " AND ".join(filters)

        query = f"""
            SELECT
                {group_expr} AS grp,
                COUNT(*) AS n,
                ROUND(COUNTIF({label_col} > 0) / COUNT(*), 4) AS win_rate,
                ROUND(AVG({label_col}), 4) AS avg_return,
                ROUND(APPROX_QUANTILES({label_col}, 100)[OFFSET(50)], 4) AS median_return,
                ROUND(APPROX_QUANTILES({label_col}, 100)[OFFSET(25)], 4) AS p25_return,
                ROUND(APPROX_QUANTILES({label_col}, 100)[OFFSET(75)], 4) AS p75_return,
                ROUND(AVG(IF(o.opp_status = 'OK', o.opp_peak_return, NULL)), 4) AS avg_mfe,
                ROUND(AVG(IF(o.opp_status = 'OK', o.opp_trough_return, NULL)), 4) AS avg_mae
            FROM {_FEATURES_VIEW} f
            JOIN {_OUTCOMES_TABLE} o
              USING (scan_date, ticker, recommended_contract)
            WHERE {where}
              AND {label_col} IS NOT NULL
              AND NOT {illiq}
            GROUP BY grp
            ORDER BY n DESC
            LIMIT 50
        """
        meta_query = f"""
            SELECT
                COUNT(*) AS pool_rows_in_window,
                COUNTIF({label_col} IS NULL) AS excluded_null_label,
                COUNTIF({label_col} IS NOT NULL AND {illiq}) AS excluded_illiquid
            FROM {_FEATURES_VIEW} f
            JOIN {_OUTCOMES_TABLE} o
              USING (scan_date, ticker, recommended_contract)
            WHERE {where}
        """

        groups = [
            _serialize(dict(r))
            for r in client.query(
                query, job_config=bigquery.QueryJobConfig(query_parameters=params)
            ).result()
        ]
        meta_row = next(
            iter(
                client.query(
                    meta_query, job_config=bigquery.QueryJobConfig(query_parameters=params)
                ).result()
            ),
            None,
        )

        return {
            "horizon": horizon,
            "group_by": group_by,
            "groups": groups,
            "meta": {
                "pool_rows_in_window": meta_row.pool_rows_in_window if meta_row else None,
                "excluded_null_label": meta_row.excluded_null_label if meta_row else None,
                "excluded_illiquid": meta_row.excluded_illiquid if meta_row else None,
                "disclaimer": _COMPOSITE_DISCLAIMER,
            },
        }

    except Exception as e:
        return {"error": safe_error(e, "get_outcome_summary")}


def estimate_exit_rule(
    target_pct: float,
    stop_pct: float,
    horizon: str = "3d",
    scan_date_from: str | None = None,
    scan_date_to: str | None = None,
) -> dict[str, Any]:
    """
    RESEARCH-ONLY — "bring your exit, we score it": classify every
    closed-window pool contract against YOUR bracket (target/stop) using the
    realized opportunity surface (MFE/MAE extremes over the 3-trading-day
    window).

    This tool surfaces excursion EVIDENCE; it does not prescribe or validate
    an exit — the exit is yours. Measured context (2026-07-06 pool study):
    every fixed target <= +80% tested EV-NEGATIVE pool-wide, because cheap
    targets amputate the right tail that pays for the ~half of contracts that
    never pop. Read any single bracket's stats as a description of the
    surface, never as a strategy.

    Classification per contract:
      * TARGET      — peak reached your target and the trough never breached
                      your stop (definitive).
      * STOP        — trough breached your stop and the peak never reached
                      your target (definitive).
      * TARGET_HEURISTIC / STOP_HEURISTIC — BOTH levels were crossed inside
                      the window. First-crossing order is not recoverable from
                      extremes alone, so the row is resolved by which EXTREME
                      came first (minutes_to_peak vs minutes_to_trough) and
                      tagged as heuristic. Treat these as best-effort, not
                      exact — the heuristic share is reported so you can bound
                      results with and without it.
      * TIMEOUT     — neither level was hit; the true exit return is unknown
                      (window-end price is not stored) but bounded by
                      [avg MAE, avg MFE] of the timeout group.

    Also returns `exact_label_match` when your bracket equals a rule the
    engine labels exactly: same_day +40/-30 (`realized_return_pct`, the live
    V7.1 GIGO policy) or 3d +80/-60 (`realized_return_pct_3d`) — exact labels
    include real fill/slippage mechanics and beat any surface estimate.

    Args:
        target_pct: Profit target in PERCENT of entry premium (e.g. 40 = +40%).
            Clamped 5-300.
        stop_pct: Stop in PERCENT (e.g. -30 or 30 both mean a -30% stop).
            Clamped magnitude 5-95.
        horizon: Only "3d" is supported for surface classification (the
            excursion window is 3 trading days). "same_day" returns exact-label
            stats only when the bracket matches +40/-30, else an explanation.
        scan_date_from / scan_date_to: YYYY-MM-DD range bounds (inclusive).

    Returns:
        {params, n_classified, buckets, est_win_rate, ev_bounds,
         exact_label_match?, meta}
    """
    if not client:
        return {"error": "BigQuery client not initialized"}

    if horizon not in ("3d", "same_day"):
        return {"error": "horizon must be '3d' or 'same_day'"}

    t = max(5.0, min(300.0, abs(float(target_pct)))) / 100.0
    s = -max(5.0, min(95.0, abs(float(stop_pct)))) / 100.0

    try:
        filters = ["TRUE"]
        params: list = [
            bigquery.ScalarQueryParameter("t", "FLOAT64", t),
            bigquery.ScalarQueryParameter("s", "FLOAT64", s),
        ]
        if scan_date_from:
            filters.append("scan_date >= @dfrom")
            params.append(bigquery.ScalarQueryParameter("dfrom", "DATE", scan_date_from))
        if scan_date_to:
            filters.append("scan_date <= @dto")
            params.append(bigquery.ScalarQueryParameter("dto", "DATE", scan_date_to))
        where = " AND ".join(filters)

        result: dict[str, Any] = {
            "params": {
                "target_pct": round(t * 100, 2),
                "stop_pct": round(s * 100, 2),
                "horizon": horizon,
                "window": "3 trading days incl. entry day, 10:00 ET entry, 15:50 ET window end",
            },
        }

        # --- exact-label stats when the bracket matches an engine-labeled rule ---
        rule = _EXACT_LABEL_RULES[horizon]
        is_exact = abs(t - rule["target"]) < 1e-9 and abs(abs(s) - rule["stop"]) < 1e-9
        if is_exact:
            lc = rule["label_col"]
            illiq = "IFNULL(illiquid_exit, FALSE)" if horizon == "same_day" else "FALSE"
            q = f"""
                SELECT
                    COUNT(*) AS n,
                    ROUND(SAFE_DIVIDE(COUNTIF({lc} > 0), COUNT(*)), 4) AS win_rate,
                    ROUND(AVG({lc}), 4) AS avg_return,
                    ROUND(APPROX_QUANTILES({lc}, 100)[OFFSET(50)], 4) AS median_return
                FROM {_OUTCOMES_TABLE}
                WHERE {where} AND {lc} IS NOT NULL AND NOT {illiq}
            """
            row = next(
                iter(
                    client.query(
                        q, job_config=bigquery.QueryJobConfig(query_parameters=params)
                    ).result()
                ),
                None,
            )
            if row:
                result["exact_label_match"] = {
                    "label": lc.replace("o.", ""),
                    "note": "Engine-simulated exact bracket (real fills, slippage, ambiguity rules).",
                    **_serialize(dict(row)),
                }

        if horizon == "same_day":
            if not is_exact:
                result["error"] = (
                    "Surface-based classification only supports horizon='3d' (the "
                    "excursion window). For same_day, only the exact +40/-30 live "
                    "bracket is labeled; other same-day brackets need minute-path "
                    "data the substrate does not store yet."
                )
            return result

        # --- surface classification over the 3-trading-day window ---
        q = f"""
            WITH classified AS (
                SELECT
                    CASE
                        WHEN opp_peak_return >= @t AND opp_trough_return > @s THEN 'TARGET'
                        WHEN opp_peak_return < @t AND opp_trough_return <= @s THEN 'STOP'
                        WHEN opp_peak_return >= @t AND opp_trough_return <= @s THEN
                            IF(opp_minutes_to_peak <= opp_minutes_to_trough,
                               'TARGET_HEURISTIC', 'STOP_HEURISTIC')
                        ELSE 'TIMEOUT'
                    END AS bucket,
                    opp_peak_return, opp_trough_return
                FROM {_OUTCOMES_TABLE}
                WHERE {where} AND opp_status = 'OK'
            )
            SELECT
                bucket,
                COUNT(*) AS n,
                ROUND(AVG(opp_peak_return), 4) AS avg_mfe,
                ROUND(AVG(opp_trough_return), 4) AS avg_mae
            FROM classified
            GROUP BY bucket
        """
        buckets = {
            r.bucket: {"n": r.n, "avg_mfe": r.avg_mfe, "avg_mae": r.avg_mae}
            for r in client.query(
                q, job_config=bigquery.QueryJobConfig(query_parameters=params)
            ).result()
        }

        n = sum(b["n"] for b in buckets.values())
        if n == 0:
            result["n_classified"] = 0
            result["buckets"] = {}
            result["meta"] = {"note": "No closed-window rows matched the date filters."}
            return result

        n_target = buckets.get("TARGET", {}).get("n", 0)
        n_stop = buckets.get("STOP", {}).get("n", 0)
        n_th = buckets.get("TARGET_HEURISTIC", {}).get("n", 0)
        n_sh = buckets.get("STOP_HEURISTIC", {}).get("n", 0)
        n_to = buckets.get("TIMEOUT", {}).get("n", 0)
        to_mfe = buckets.get("TIMEOUT", {}).get("avg_mfe") or 0.0
        to_mae = buckets.get("TIMEOUT", {}).get("avg_mae") or 0.0

        # EV bounds: definitive + heuristic rows realize their level; TIMEOUT
        # rows are bounded by the timeout group's [avg MAE, avg MFE].
        wins = n_target + n_th
        losses = n_stop + n_sh
        ev_low = (wins * t + losses * s + n_to * to_mae) / n
        ev_high = (wins * t + losses * s + n_to * to_mfe) / n

        result.update(
            {
                "n_classified": n,
                "buckets": buckets,
                "heuristic_share": round((n_th + n_sh) / n, 4),
                "est_win_rate": round(wins / n, 4),
                "est_win_rate_definitive_only": (
                    round(n_target / (n_target + n_stop + n_to), 4)
                    if (n_target + n_stop + n_to) > 0
                    else None
                ),
                "ev_bounds": {
                    "low": round(ev_low, 4),
                    "high": round(ev_high, 4),
                    "note": (
                        "FRACTION units. TIMEOUT rows' true exit return is unknown "
                        "(no window-end price stored) — bounds use the timeout "
                        "group's avg MAE (low) and avg MFE (high). No exit slippage "
                        "applied. _HEURISTIC buckets resolved by extreme order, not "
                        "first-crossing — check heuristic_share."
                    ),
                },
                "meta": {
                    "research_only": (
                        "Excursion evidence, not exit advice — no fixed bracket "
                        "tested EV-positive pool-wide (2026-07-06 study)."
                    ),
                    "disclaimer": _COMPOSITE_DISCLAIMER,
                },
            }
        )
        return result

    except Exception as e:
        return {"error": safe_error(e, "estimate_exit_rule")}


def get_regime_context(scan_date: str | None = None) -> dict[str, Any]:
    """
    Point-in-time market-regime context for a scan date: VIX close, VIX3M,
    SPY trend state, and the 5-day VIX delta — all as-of <= scan_date (the
    selection point, leakage-safe), plus the engine's regime safety rail
    evaluated on those values.

    The rail: the engine fail-closes (no trade) when spot VIX > VIX3M
    (backwardation — the market pricing imminent volatility is an adverse
    regime for short-dated directional longs).

    Served from the labeled substrate, which lags the live pool by ~1-2
    trading days. Values are constant per scan_date.

    Args:
        scan_date: YYYY-MM-DD. Defaults to the latest scan date carrying
            regime features.

    Returns:
        {scan_date, vix_at_scan, vix3m_at_enrich, spy_trend_at_scan,
         vix_5d_delta_at_scan, regime_rail_pass, rail_definition}
    """
    if not client:
        return {"error": "BigQuery client not initialized"}

    try:
        if not scan_date:
            scan_date = _latest_scan_date(_OUTCOMES_TABLE, "vix_at_scan IS NOT NULL")
        if not scan_date:
            return {"error": "No regime data found"}

        q = f"""
            SELECT
                CAST(scan_date AS STRING) AS scan_date,
                ANY_VALUE(vix_at_scan) AS vix_at_scan,
                ANY_VALUE(vix3m_at_enrich) AS vix3m_at_enrich,
                ANY_VALUE(spy_trend_at_scan) AS spy_trend_at_scan,
                ANY_VALUE(vix_5d_delta_at_scan) AS vix_5d_delta_at_scan
            FROM {_OUTCOMES_TABLE}
            WHERE scan_date = @scan_date
            GROUP BY scan_date
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("scan_date", "DATE", scan_date)]
        )
        row = next(iter(client.query(q, job_config=job_config).result()), None)
        if not row:
            return {"error": f"No regime data for scan_date {scan_date}"}

        r = dict(row)
        vix, vix3m = r.get("vix_at_scan"), r.get("vix3m_at_enrich")
        r["regime_rail_pass"] = (vix <= vix3m) if (vix is not None and vix3m is not None) else None
        latest = _latest_scan_date(_OUTCOMES_TABLE, "vix_at_scan IS NOT NULL")
        r["latest_available_scan_date"] = latest
        r["lag_note"] = (
            "Regime is computed per scan_date on the LABELED substrate, which "
            f"lags the live pool by ~1-2 trading days (latest available: {latest}). "
            "For a decision today, treat this as the most recent CLOSED session's "
            "regime unless the dates match."
        )
        r["rail_definition"] = (
            "PASS when VIX <= VIX3M (contango). FAIL (engine fail-closes, no "
            "trade) when spot VIX exceeds 3-month VIX (backwardation). Values "
            "are closes as-of the scan date — known before any entry decision."
        )
        return r

    except Exception as e:
        return {"error": safe_error(e, "get_regime_context")}


def _wilson_ci(k: int, n: int, z: float = 1.96) -> list[float] | None:
    if n == 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) * z / denom
    return [round(center - half, 4), round(center + half, 4)]


def _trading_day_bucket(entry_day, peak_dt_et) -> str:
    """Which trading day of the window the peak landed on (day1/day2/day3).
    Weekday arithmetic — market holidays inside a window can shift a bucket
    by one day (documented in the tool's meta)."""
    peak_date = peak_dt_et.date()
    if peak_date <= entry_day:
        return "day1"
    d, idx = entry_day, 1
    while d < peak_date and idx < 3:
        d += _ONE_DAY
        if d.weekday() < 5:
            idx += 1
    return f"day{idx}"


def get_harvest_curve(
    targets: list[float] | None = None,
    stops: list[float] | None = None,
    scan_date_from: str | None = None,
    scan_date_to: str | None = None,
    delta_min: float | None = None,
    delta_max: float | None = None,
) -> dict[str, Any]:
    """
    The HARVEST CURVE — for each profit target X, the probability a pool
    contract's premium TOUCHED +X% at least once inside the 3-trading-day
    excursion window (10:00 ET entry), with confidence intervals, which day
    the peak landed on, and stop-touch rates. Computed live from the closed-
    window opportunity surface, so it moves as data accrues.

    This is the ceiling for any limit-at-+X% exit: a TOUCH IS NOT A FILL (bar-
    high events, no exit slippage). Measured context (2026-07-06 study): about
    half of contracts touch +20%, ~1 in 7 touches +100%, meaningful pops land
    on day 2-3 not day 1, and every FIXED target tested EV-negative pool-wide
    — use this curve to understand the surface, not as a strategy return.

    Args:
        targets: Profit targets in PERCENT (default [15,20,30,50,75,100]);
            each clamped 5-300, max 12 values.
        stops: Stop levels in PERCENT magnitude (default [30,60]); each
            clamped 5-95, max 6 values.
        scan_date_from / scan_date_to: YYYY-MM-DD range bounds (inclusive).
        delta_min / delta_max: Bounds on |recommended_delta| (0-1).

    Returns:
        {window, n, median_peak_return, targets: [{target_pct, p_touch,
         ci95, n_touch, day_of_peak: {day1,day2,day3}}], stops: [{stop_pct,
         p_touch, ci95}], meta}
    """
    if not client:
        return {"error": "BigQuery client not initialized"}

    try:
        tgts = sorted(
            {max(5.0, min(300.0, abs(float(t)))) for t in (targets or [15, 20, 30, 50, 75, 100])}
        )[:12]
        stps = sorted({max(5.0, min(95.0, abs(float(s)))) for s in (stops or [30, 60])})[:6]

        filters = ["o.opp_status = 'OK'", "o.opp_peak_return IS NOT NULL"]
        params: list = []
        if scan_date_from:
            filters.append("f.scan_date >= @dfrom")
            params.append(bigquery.ScalarQueryParameter("dfrom", "DATE", scan_date_from))
        if scan_date_to:
            filters.append("f.scan_date <= @dto")
            params.append(bigquery.ScalarQueryParameter("dto", "DATE", scan_date_to))
        if delta_min is not None:
            filters.append("ABS(f.recommended_delta) >= @dmin")
            params.append(bigquery.ScalarQueryParameter("dmin", "FLOAT64", float(delta_min)))
        if delta_max is not None:
            filters.append("ABS(f.recommended_delta) <= @dmax")
            params.append(bigquery.ScalarQueryParameter("dmax", "FLOAT64", float(delta_max)))
        where = " AND ".join(filters)

        query = f"""
            SELECT
                o.opp_peak_return AS peak,
                o.opp_trough_return AS trough,
                o.opp_minutes_to_peak AS mins,
                o.opp_entry_timestamp AS entry_ts,
                o.entry_day AS entry_day
            FROM {_FEATURES_VIEW} f
            JOIN {_OUTCOMES_TABLE} o
              USING (scan_date, ticker, recommended_contract)
            WHERE {where}
            LIMIT 20000
        """
        meta_query = f"""
            SELECT
                COUNT(*) AS pool_rows_in_window,
                COUNTIF(NOT (o.opp_status = 'OK' AND o.opp_peak_return IS NOT NULL))
                    AS excluded_no_surface
            FROM {_FEATURES_VIEW} f
            JOIN {_OUTCOMES_TABLE} o
              USING (scan_date, ticker, recommended_contract)
            WHERE {" AND ".join(filters[2:]) if len(filters) > 2 else "TRUE"}
        """

        rows = list(
            client.query(
                query, job_config=bigquery.QueryJobConfig(query_parameters=params)
            ).result()
        )
        meta_row = next(
            iter(
                client.query(
                    meta_query, job_config=bigquery.QueryJobConfig(query_parameters=params)
                ).result()
            ),
            None,
        )

        n = len(rows)
        truncated = n >= 20000
        if n == 0:
            return {
                "n": 0,
                "targets": [],
                "stops": [],
                "meta": {"note": "No closed-window rows matched the filters."},
            }

        peaks = sorted(float(r.peak) for r in rows)
        median_peak = peaks[n // 2] if n % 2 else (peaks[n // 2 - 1] + peaks[n // 2]) / 2

        # Pre-compute day-of-peak buckets once per row.
        buckets: list[str] = []
        for r in rows:
            if r.entry_ts is not None and r.mins is not None and r.entry_day is not None:
                peak_dt_et = (r.entry_ts + _timedelta(minutes=float(r.mins))).astimezone(_ET_TZ)
                buckets.append(_trading_day_bucket(r.entry_day, peak_dt_et))
            else:
                buckets.append("unknown")

        target_out = []
        for t in tgts:
            x = t / 100.0
            hits = [i for i, r in enumerate(rows) if float(r.peak) >= x]
            k = len(hits)
            day_counts = {"day1": 0, "day2": 0, "day3": 0}
            for i in hits:
                if buckets[i] in day_counts:
                    day_counts[buckets[i]] += 1
            target_out.append(
                {
                    "target_pct": t,
                    "p_touch": round(k / n, 4),
                    "ci95": _wilson_ci(k, n),
                    "n_touch": k,
                    "day_of_peak": day_counts,
                }
            )

        stop_out = []
        for s in stps:
            x = -s / 100.0
            k = sum(1 for r in rows if r.trough is not None and float(r.trough) <= x)
            stop_out.append({"stop_pct": -s, "p_touch": round(k / n, 4), "ci95": _wilson_ci(k, n)})

        return {
            "window": "3 trading days incl. entry day, 10:00 ET entry, 15:50 ET window end",
            "n": n,
            "truncated": truncated,
            "median_peak_return": round(median_peak, 4),
            "targets": target_out,
            "stops": stop_out,
            "meta": {
                "pool_rows_in_window": meta_row.pool_rows_in_window if meta_row else None,
                "excluded_no_surface": meta_row.excluded_no_surface if meta_row else None,
                "note": (
                    "TOUCH-BASED CEILING: bar-high events, no exit slippage — a "
                    "touch is not a fill. day_of_peak is the day of the WINDOW "
                    "MAXIMUM among touching rows (weekday arithmetic; a market "
                    "holiday inside a window can shift a bucket by one day). The "
                    "excluded illiquid/open tail is non-random. " + _COMPOSITE_DISCLAIMER
                ),
            },
        }

    except Exception as e:
        return {"error": safe_error(e, "get_harvest_curve")}
