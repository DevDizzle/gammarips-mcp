"""
GammaRips MCP V4 — the 9 consolidated tool handlers.

V4 collapses the 29-tool V3 surface into 9 tools (ratified 2026-07-17
simplification replan). Each handler is a thin, arg-driven dispatcher over
the EXISTING, already-leakage-audited query logic in the sibling tool
modules — the underlying functions are reused verbatim (imported here as
`_*_impl`), so V4 changes the SURFACE, not the physics. Nothing about the
leakage-safe views, pick-flag guards, cohort discipline, or redaction
changes; those live in the implementations this module calls.

The frozen 9-tool map (names are contract-frozen — downstream repos rename
against them):

  get_pool                 free   pool: enriched | raw | features | preview
  get_signal               pro    single ticker: detail | earnings
  get_liquidity            pro    fresh liquidity: one contract | whole pool
  query_outcomes           pro    outcomes/receipts substrate (view= modes)
  replay_contract          pro    price tape: minute path | daily marks
  get_regime_context       free   VIX/VIX3M regime rail (unchanged)
  get_market_calendar_status free NYSE status | available scan dates
  get_playbook             free   methodology | field dict | data-contract schema
  get_daily_report         free   full report | recent-report list

KILLED in V4: web_search.
"""

from __future__ import annotations

from typing import Any

# --- reused V3 implementations (the leakage-audited query logic) -----------
from tools.contract_history import get_contract_marks as _get_contract_marks_impl
from tools.contract_history import replay_contract as _replay_contract_impl
from tools.earnings import get_earnings_window as _get_earnings_window_impl
from tools.education import get_market_calendar_status as _get_market_calendar_status_impl
from tools.education import get_signal_explainer as _get_signal_explainer_impl
from tools.historical import get_historical_performance as _get_historical_performance_impl
from tools.market_snapshot import get_contract_snapshot as _get_contract_snapshot_impl
from tools.market_snapshot import get_pool_liquidity as _get_pool_liquidity_impl
from tools.metadata import get_available_dates as _get_available_dates_impl
from tools.metadata import get_enriched_signal_schema as _get_enriched_signal_schema_impl
from tools.overnight_signals import get_enriched_signals as _get_enriched_signals_impl
from tools.overnight_signals import get_freemium_preview as _get_freemium_preview_impl
from tools.overnight_signals import get_overnight_signals as _get_overnight_signals_impl
from tools.overnight_signals import get_signal_detail as _get_signal_detail_impl
from tools.performance_tracker import get_position_history as _get_position_history_impl
from tools.performance_tracker import get_signal_performance as _get_signal_performance_impl
from tools.performance_tracker import get_win_rate_summary as _get_win_rate_summary_impl
from tools.playbooks import get_playbook as _get_playbook_impl
from tools.playbooks import list_playbooks as _list_playbooks_impl
from tools.reports import get_daily_report as _get_daily_report_impl
from tools.reports import get_report_list as _get_report_list_impl

# get_regime_context is UNCHANGED — re-exported directly so it registers under
# its own name with its own (already agent-facing) docstring/signature.
from tools.substrate import estimate_exit_rule as _estimate_exit_rule_impl
from tools.substrate import get_harvest_curve as _get_harvest_curve_impl
from tools.substrate import get_opportunity_surface as _get_opportunity_surface_impl
from tools.substrate import get_outcome_summary as _get_outcome_summary_impl
from tools.substrate import get_pool_features as _get_pool_features_impl
from tools.substrate import get_regime_context  # noqa: F401  (re-exported as a tool)
from tools.substrate import query_outcomes as _query_outcomes_impl
from utils.data import LIVE_POLICY_VERSION


def _bad(param: str, value: Any, allowed: list[str]) -> dict[str, Any]:
    return {
        "error": f"unknown {param}={value!r}",
        "allowed": allowed,
    }


# ===========================================================================
# 1. get_pool  (free)  — the candidate pool, four views
# ===========================================================================
def get_pool(
    view: str = "enriched",
    scan_date: str | None = None,
    direction: str | None = None,
    ticker: str | None = None,
    min_score: int = 0,
    limit: int = 25,
    summary: bool = True,
    fields: list[str] | None = None,
    offset: int = 0,
) -> Any:
    """
    The GammaRips candidate pool for a scan date. One tool, four `view`s:

      * view="enriched" (DEFAULT) — the curated AI-enriched pool: news,
        technicals, catalyst, a delta-targeted recommended contract, and the
        60-day momentum feature `mom_60`. Enrichment gate: overnight_score>=1
        AND directional UOA>$500K, edge-ranked to the top ~50 BULLISH names
        (the score floor is cosmetic; the UOA bar, the BULLISH gate, and
        the top-50 cap do the filtering).
        This is the daily candidate set your agent reasons over to its OWN
        contract (see get_playbook("run-your-own-tournament")). Served from a
        leakage-safe view (forward-outcome columns physically stripped);
        `summary=True` gives ~21 decision columns, `fields=[...]` a strict
        projection, `summary=False` full rows, `offset` pages.
      * view="raw" — the wide pre-curation overnight scan (where unusual
        options activity concentrated across the whole universe, BEFORE
        curation). Honors `direction`, `min_score`, `ticker`, `limit`.
      * view="features" — point-in-time FEATURE VECTORS from the leakage-safe
        allowlist view `enriched_features_v1` (identity + features + cohort
        metadata only; no outcome/label/telemetry column can appear). The
        quantitative substrate for joining against query_outcomes. Lags the
        live pool by ~1-2 trading days.
      * view="preview" — a minimal public teaser (ticker, direction, score,
        headline, directional UOA) for the most recent scan; no contract
        specifics or thesis.

    TIER: view="preview" is FREE (no key). The enriched / raw / features views
    are the paid product — they require an active pro subscription key; an anon
    call to them returns `subscription_required` (get_pool(view='preview') is
    named as the free entry point).

    Liquidity caveat (all views): `recommended_oi`/`recommended_volume` are
    scan-time snapshots, not live values; `recommended_spread_pct` is
    permanently NULL on the current data plan — re-check with get_liquidity.

    Args:
        view: "enriched" (default) | "raw" | "features" | "preview".
        scan_date: YYYY-MM-DD (default: latest available scan for the view).
        direction: "bull"/"bear" prefix filter (enriched / raw).
        ticker: exact ticker filter (enriched / raw / features).
        min_score: overnight_score floor (raw view only; clamped 0-10).
        limit: max rows (enriched/raw clamp 1-50, features 1-100, preview 1-20).
        summary: enriched only — True=compact columns, False=full rows.
        fields: enriched only — explicit strict column projection.
        offset: enriched only — pagination offset.
    """
    v = (view or "enriched").strip().lower()
    if v == "enriched":
        return _get_enriched_signals_impl(
            scan_date=scan_date,
            direction=direction,
            ticker=ticker,
            limit=limit,
            summary=summary,
            fields=fields,
            offset=offset,
        )
    if v == "raw":
        return _get_overnight_signals_impl(
            scan_date=scan_date,
            direction=direction,
            min_score=min_score,
            ticker=ticker,
            limit=limit,
        )
    if v == "features":
        return _get_pool_features_impl(scan_date=scan_date, ticker=ticker, limit=limit)
    if v == "preview":
        return _get_freemium_preview_impl(limit=limit)
    return _bad("view", view, ["enriched", "raw", "features", "preview"])


# ===========================================================================
# 2. get_signal  (pro)  — one ticker: enrichment detail OR earnings window
# ===========================================================================
def get_signal(
    ticker: str | None = None,
    view: str = "detail",
    scan_date: str | None = None,
    full: bool = False,
    expiration: str | None = None,
    contract: str | None = None,
) -> dict[str, Any]:
    """
    Deep dive on a single ticker/contract. Two `view`s:

      * view="detail" (DEFAULT) — the full enriched signal for one ticker:
        thesis, catalyst, the recommended contract, and point-in-time
        features (leakage-safe view). `full=true` includes the long narrative
        (news_summary, flow_intent_reasoning). If the ticker isn't in the
        pool for the date, the error lists the dates on which it does appear.
      * view="earnings" — the doctrine earnings-window check (RM-003): the
        next scheduled earnings date and whether it lands ON OR BEFORE the
        contract expiration (`earnings_in_window`). The engine applies this
        rail only at its own pick time, NOT in the pool, so pool rows CAN
        carry earnings-window names — check every candidate yourself. Pass
        the pool's `recommended_contract` and both ticker and expiration are
        derived. FAIL-CLOSED: unknown date -> earnings_in_window=null, treat
        as in-window.

    Args:
        ticker: underlying symbol (required for detail; optional for earnings
            if `contract` is given).
        view: "detail" (default) | "earnings".
        scan_date: detail only — YYYY-MM-DD (default: latest for the ticker).
        full: detail only — include the long narrative fields.
        expiration: earnings only — option expiration YYYY-MM-DD to test.
        contract: earnings only — OCC ticker supplying ticker+expiration.
    """
    v = (view or "detail").strip().lower()
    if v == "detail":
        if not ticker:
            return {"error": "view='detail' requires ticker"}
        return _get_signal_detail_impl(ticker=ticker, scan_date=scan_date, full=full)
    if v == "earnings":
        return _get_earnings_window_impl(ticker=ticker, expiration=expiration, contract=contract)
    return {"error": f"unknown view={view!r}", "allowed": ["detail", "earnings"]}


# ===========================================================================
# 3. get_liquidity  (pro)  — fresh entry-day liquidity
# ===========================================================================
def get_liquidity(
    contract: str | None = None,
    scan_date: str | None = None,
    contracts: list[str] | None = None,
    live: bool = False,
) -> dict[str, Any]:
    """
    FRESH (entry-day) liquidity — the read the pool's session-frozen
    `recommended_oi`/`recommended_volume` cannot give you (the overnight sweep
    only becomes OI the next morning). Two modes, chosen by whether you pass a
    single `contract`:

      * `contract` given — ONE contract's snapshot: open interest, session
        volume, last trade, day range, underlying price, greeks. Cache-first
        (the engine re-reads the pool every ~10 min in market hours); pass
        live=true to force a fresh upstream fetch or read a contract NOT in
        today's pool.
      * `contract` omitted — the WHOLE current pool (or your `contracts`
        shortlist, max 60) in ONE call — the batch companion for the ~10:00 ET
        decision window. Most-recent read per contract with explicit `as_of`.

    Deliberately serves NO bid/ask/mid/spread (not available on the current
    data plan — absent, not NULL). Judge fill risk from open_interest (updates
    once each morning), day_volume (live session), last_trade recency, and the
    day range.

    Args:
        contract: OCC ticker for the single-contract mode (verbatim from the
            pool's `recommended_contract`). Omit for the whole-pool batch.
        scan_date: pool date YYYY-MM-DD (batch mode; default: latest pool).
        contracts: optional shortlist filter for the batch mode (max 60).
        live: single-contract mode — force a fresh upstream fetch.
    """
    if contract:
        return _get_contract_snapshot_impl(contract=contract, live=live)
    return _get_pool_liquidity_impl(scan_date=scan_date, contracts=contracts)


# ===========================================================================
# 4. query_outcomes  (pro)  — the outcomes/receipts substrate, via view=
# ===========================================================================
def query_outcomes(
    view: str = "labels",
    horizon: str | None = None,
    group_by: str = "none",
    scan_date: str | None = None,
    scan_date_from: str | None = None,
    scan_date_to: str | None = None,
    ticker: str | None = None,
    direction: str | None = None,
    delta_min: float | None = None,
    delta_max: float | None = None,
    min_overnight_score: int | None = None,
    exit_reason: str | None = None,
    outcome: str | None = None,
    days: int = 30,
    limit: int = 100,
    aggregate_only: bool = False,
    include_open: bool = False,
    targets: list[float] | None = None,
    stops: list[float] | None = None,
    target_pct: float | None = None,
    stop_pct: float = 30,
    rule: str = "bracket",
    trail_pct: float | None = None,
    activation_pct: float = 0,
    policy_version: str | None = LIVE_POLICY_VERSION,
    min_premium_score: int | None = None,
) -> dict[str, Any]:
    """
    The realized-outcome + receipts substrate behind the engine. One tool,
    nine `view`s. Whole-pool composites under any FIXED exit are NEGATIVE by
    construction — these are a research surface (how outcomes distribute
    across features and exits), never a strategy track record.

      * view="labels" (DEFAULT) — row-level realized bracket LABELS joined to
        point-in-time features. horizon "same_day" (live V7.1 GIGO +40/-30) or
        "3d" (legacy +80/-60) — never pooled. NULL-label and illiquid rows
        excluded (counts in meta). `aggregate_only=True` returns summary stats
        instead of rows. Filters: scan_date_from/to, ticker, delta_min/max,
        min_overnight_score, exit_reason.
      * view="summary" — grouped aggregates over the labeled pool. `group_by`
        one of none|delta_bucket|overnight_score|premium_score|exit_reason|
        day_of_week|moneyness_bucket.
      * view="surface" — the OPPORTUNITY SURFACE: per-contract realized MFE/MAE
        excursions with NO exit applied (profit potential, exit free). Uses
        scan_date OR a `days` lookback, `ticker`, `delta_min/max`,
        `include_open`. `aggregate_only=True` returns MFE/MAE quantiles over
        the FULL filtered set — use it for exit design. The row mode is capped
        at 200 and truncates oldest-first WITHIN a scan_date, so its oldest
        date is a highest-MFE-only slice; it reports `truncated`,
        `matched_rows`, and `partial_scan_date` so you can see that happen.
      * view="harvest" — the touch-probability curve: P(premium touched +X%)
        with CIs, day-of-peak buckets, stop-touch rates. `targets`, `stops`,
        date range, delta band.
      * view="exit_rule" — RESEARCH-ONLY "bring your exit, we score it":
        rule="bracket" (target_pct/stop_pct) or rule="trailing" (trail_pct,
        activation_pct) scored against the surface / minute tape.
      * view="signal_performance" — UNDERLYING-STOCK direction outcomes for
        the broad pool (NOT option PnL). Filters scan_date, ticker, direction,
        outcome.
      * view="win_rate" — aggregate UNDERLYING-direction win rate over `days`
        (NOT option PnL; headline key carries its universe).
      * view="positions" — the RECEIPTS: realized (closed) paper trades from
        the engine's own daily pick, row-level, cohort-filtered
        (`policy_version`, default live). Over `days`, `limit`.
      * view="performance" — cohort AGGREGATE of the receipts over `days`
        (win rate, avg/median/best/worst), `direction`, `min_premium_score`,
        `policy_version`. When the cohort has no closed trades, every aggregate
        is `null` and `total_trades` is 0 — NEVER 0.0. A `null` here means "not
        measured yet", not "zero percent"; do not render it as a result.

    All returns are FRACTIONS (0.40 = +40%). Realized data serves closed
    windows only. Paper-traded research data; not investment advice.

    Args:
        view: which surface (see above). Default "labels".
        horizon: "same_day" | "3d" (labels/summary/exit_rule). If omitted, the
            native default per view is used: labels/summary => "same_day" (the
            live GIGO policy), exit_rule => "3d" (its excursion window).
        group_by: summary grouping dimension.
        scan_date / scan_date_from / scan_date_to: date filters (per view).
        ticker / direction / delta_min / delta_max / min_overnight_score /
            exit_reason / outcome: row/aggregate filters (per view).
        days: lookback window (surface/win_rate/positions/performance).
        limit: max rows (labels 1-200, signal_performance 1-50, positions 1-200).
        aggregate_only: labels/surface views — summary stats instead of rows.
            On `surface` this is also the only mode immune to the 200-row cap.
        include_open: surface view — include not-yet-closed windows.
        targets / stops: harvest view — PERCENT grids.
        target_pct / stop_pct / rule / trail_pct / activation_pct: exit_rule view.
        policy_version: positions/performance cohort filter. The live default
            is the PAIR (policy label + cohort start date) — the label alone
            does not define the cohort, since disowned cohorts remain in the
            ledger under the same label. Responses carry `cohort_start`; a zero
            row_count under the live cohort means it has not accrued closed
            trades yet, not that there is no track record, and the aggregates
            come back `null` rather than 0.0. Pass "all" for every era, but
            note that "all" returns cohorts the engine has REPUDIATED — not
            merely older exit mechanics — so it is not a track record and must
            not be aggregated into one. Read the response `note` before
            quoting any number from it.
        min_premium_score: performance view floor.
    """
    v = (view or "labels").strip().lower()
    # Per-view native horizon default preserved (labels/summary => "same_day",
    # the live GIGO policy; exit_rule => "3d", its excursion window). A shared
    # scalar default would silently change one of them, so resolve per view.
    if v == "labels":
        return _query_outcomes_impl(
            horizon=horizon or "same_day",
            scan_date_from=scan_date_from,
            scan_date_to=scan_date_to,
            ticker=ticker,
            delta_min=delta_min,
            delta_max=delta_max,
            min_overnight_score=min_overnight_score,
            exit_reason=exit_reason,
            limit=limit,
            aggregate_only=aggregate_only,
        )
    if v == "summary":
        return _get_outcome_summary_impl(
            horizon=horizon or "same_day",
            group_by=group_by,
            scan_date_from=scan_date_from,
            scan_date_to=scan_date_to,
        )
    if v == "surface":
        return _get_opportunity_surface_impl(
            scan_date=scan_date,
            ticker=ticker,
            days=days,
            include_open=include_open,
            aggregate_only=aggregate_only,
            delta_min=delta_min,
            delta_max=delta_max,
        )
    if v == "harvest":
        return _get_harvest_curve_impl(
            targets=targets,
            stops=stops,
            scan_date_from=scan_date_from,
            scan_date_to=scan_date_to,
            delta_min=delta_min,
            delta_max=delta_max,
        )
    if v == "exit_rule":
        return _estimate_exit_rule_impl(
            target_pct=target_pct,
            stop_pct=stop_pct,
            horizon=horizon or "3d",
            scan_date_from=scan_date_from,
            scan_date_to=scan_date_to,
            rule=rule,
            trail_pct=trail_pct,
            activation_pct=activation_pct,
        )
    if v == "signal_performance":
        return _get_signal_performance_impl(
            scan_date=scan_date,
            ticker=ticker,
            direction=direction,
            outcome=outcome,
            limit=limit,
        )
    if v == "win_rate":
        return _get_win_rate_summary_impl(days=days)
    if v == "positions":
        return _get_position_history_impl(days=days, limit=limit, policy_version=policy_version)
    if v == "performance":
        return _get_historical_performance_impl(
            lookback_days=days,
            direction=direction,
            min_premium_score=min_premium_score,
            policy_version=policy_version,
        )
    return _bad(
        "view",
        view,
        [
            "labels",
            "summary",
            "surface",
            "harvest",
            "exit_rule",
            "signal_performance",
            "win_rate",
            "positions",
            "performance",
        ],
    )


# ===========================================================================
# 5. replay_contract  (pro)  — the price tape, minute or daily
# ===========================================================================
def replay_contract(
    contract: str,
    date: str | None = None,
    granularity: str = "minute",
    target_pct: float | None = None,
    stop_pct: float | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> dict[str, Any]:
    """
    Raw option price data for YOUR OWN entry/exit rule. This server does NOT
    simulate or validate exits — it returns bars (the RM-002/RM-004 boundary).
    Two `granularity` modes:

      * granularity="minute" (DEFAULT) — the intraday minute path for one
        session (`date` required). Optionally pass a bracket (target_pct/
        stop_pct, PERCENT of the 10:00 ET anchor) and the response also reports
        the exact FIRST-CROSSING sequence measured from the tape. Pool
        excursion windows are served from the engine's minute-path table;
        anything else falls back to an upstream minute fetch.
      * granularity="day" — the DAILY mark series (OHLCV) over a date range,
        to mark a live paper position day by day or replay a closed one. Uses
        `from_date`/`to_date` (span capped at 120 days); `date` is ignored.

    Option tape is THIN — minutes/days with no prints have no bar; treat
    touch times as evidence, not tick-perfect truth. Paper-trade research
    data; not investment advice.

    Args:
        contract: OCC option ticker (e.g. "O:UNIT260717C00030000").
        date: minute mode — ET session date YYYY-MM-DD (required).
        granularity: "minute" (default) | "day".
        target_pct: minute mode — optional +X% level for first-crossing.
        stop_pct: minute mode — optional -Y% level for first-crossing.
        from_date: day mode — start YYYY-MM-DD (default: 30d before to_date).
        to_date: day mode — end YYYY-MM-DD inclusive (default: today ET).
    """
    g = (granularity or "minute").strip().lower()
    if g == "minute":
        if not date:
            return {"error": "granularity='minute' requires date (the ET session, YYYY-MM-DD)"}
        return _replay_contract_impl(
            contract=contract, date=date, target_pct=target_pct, stop_pct=stop_pct
        )
    if g == "day":
        return _get_contract_marks_impl(contract=contract, from_date=from_date, to_date=to_date)
    return {"error": f"unknown granularity={granularity!r}", "allowed": ["minute", "day"]}


# ===========================================================================
# 7. get_market_calendar_status  (free)  — NYSE status OR available scan dates
# ===========================================================================
def get_market_calendar_status(view: str = "status") -> Any:
    """
    Market-calendar reference. Two `view`s:

      * view="status" (DEFAULT) — is the US equity market open today, plus the
        next open/close, holiday, and early-close flags (NYSE calendar,
        deterministic — no "is the market open?" hallucination).
      * view="scan_dates" — which recent scan dates have GammaRips data, with
        per-date signal counts (the pool's data-availability calendar).

    Args:
        view: "status" (default) | "scan_dates".
    """
    v = (view or "status").strip().lower()
    if v == "status":
        return _get_market_calendar_status_impl()
    if v == "scan_dates":
        return _get_available_dates_impl()
    return _bad("view", view, ["status", "scan_dates"])


# ===========================================================================
# 8. get_playbook  (free)  — methodology + field dict + data-contract schema
# ===========================================================================
def get_playbook(name: str | None = None, field: str | None = None) -> Any:
    """
    Methodology + reference, versioned server-side (re-fetch rather than
    caching long-term). Arg-driven:

      * `field` given — the plain-English DEFINITION + role of a signal field
        (deterministic lookup, no LLM). e.g. field="mom_60". The response's
        `available_fields` lists every documented field.
      * `name` given — a methodology playbook (markdown) by name, OR two
        special reference pages:
          - name="schema" (or "data-contract") -> the machine-readable
            substrate DATA CONTRACT: every outcome/label column with its
            leakage classification (feature|label|opportunity|
            regime_telemetry|identity) and as-of boundary. Only `feature`
            columns are safe as selection inputs.
          - any other name -> the playbook markdown (start-here,
            daily-workflow, run-your-own-tournament, exit-lab,
            leakage-and-data-contract, changelog).
      * neither — the CATALOG of published playbooks (name/title/summary),
        plus a pointer to the field dict (`field=`) and schema page.

    Args:
        name: playbook name, or "schema"/"data-contract" for the data contract.
        field: a signal field name to explain (overrides `name`).
    """
    if field:
        return _get_signal_explainer_impl(field_name=field)
    if name:
        key = name.strip().lower()
        if key in ("schema", "data-contract", "data-contract-schema", "signal-schema"):
            return _get_enriched_signal_schema_impl()
        return _get_playbook_impl(name=name)
    return {
        "playbooks": _list_playbooks_impl(),
        "reference_pages": {
            "field_dictionary": "get_playbook(field='<field_name>') — plain-English field definitions",
            "data_contract_schema": "get_playbook(name='schema') — machine-readable leakage classification",
        },
    }


# ===========================================================================
# 9. get_daily_report  (free)  — full report OR recent-report list
# ===========================================================================
def get_daily_report(date: str | None = None, view: str = "report", limit: int = 10) -> Any:
    """
    The daily intelligence report. Two `view`s:

      * view="report" (DEFAULT) — the full report (title, markdown content,
        scan_date) for `date`, or the most recent report if `date` is omitted.
      * view="list" — recent reports, most recent first (scan_date, title,
        created_at), titles deduped. Use `limit`.

    Args:
        date: report date YYYY-MM-DD (report view; default: most recent).
        view: "report" (default) | "list".
        limit: list view — how many reports (default 10, clamped 1-30).
    """
    v = (view or "report").strip().lower()
    if v == "report":
        return _get_daily_report_impl(date=date)
    if v == "list":
        return _get_report_list_impl(limit=limit)
    return _bad("view", view, ["report", "list"])
