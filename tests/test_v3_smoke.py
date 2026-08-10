"""
V4 surface smoke test — calls every registered tool (the 9 consolidated V4
handlers) against live data and asserts the leakage guarantees. The absorbed
V3 tools are exercised through their v4 view=/granularity= modes. Runnable
directly:

    PYTHONPATH=src .venv/bin/python tests/test_v3_smoke.py

or via pytest. Requires ADC with BigQuery read access.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta

from utils.data import LIVE_POLICY_VERSION

# Columns the win-tracker writes back upstream — must NEVER appear in any
# live-pool tool response (the safe view strips them).
FORWARD_OUTCOME_COLS = {
    "next_day_pct",
    "day2_pct",
    "day3_pct",
    "peak_return_3d",
    "is_win",
    "outcome_tier",
    "next_day_close",
    "day2_close",
    "day3_close",
    "performance_updated",
}

# Realized/label/telemetry columns that must NEVER appear in the features tool.
# Mirrors the exclusion groups in the engine's create_enriched_features_view.py.
NON_FEATURE_COLS = {
    # same-day label group
    "entry_timestamp",
    "entry_price",
    "target_price",
    "stop_price",
    "trail_trigger_price",
    "peak_premium",
    "trail_activated",
    "trail_stop_at_exit",
    "exit_timestamp",
    "exit_reason",
    "exit_day",
    "realized_return_pct",
    "exit_slippage",
    "illiquid_exit",
    "late_fill_minutes",
    # 3-day label group
    "realized_return_pct_3d",
    "exit_reason_3d",
    "exit_day_3d",
    "exit_timestamp_3d",
    "entry_price_3d",
    "peak_premium_3d",
    # label-semantics tags
    "label_sim_version",
    "label_hold_days",
    "label_stop_pct",
    "label_target_pct",
    "label_3d_sim_version",
    "label_3d_hold_days",
    "label_3d_stop_pct",
    "label_3d_target_pct",
    # opportunity surface
    "opp_peak_return",
    "opp_trough_return",
    "opp_minutes_to_peak",
    "opp_minutes_to_trough",
    "opp_entry_price",
    "opp_entry_timestamp",
    "opp_bar_count",
    "opp_window_days",
    "opp_status",
    "opp_sim_version",
    # entry-day-close regime telemetry + legacy leak columns
    "oc_vix_at_close",
    "oc_spy_trend_at_close",
    "oc_vix_5d_delta_at_close",
    "VIX_at_entry",
    "SPY_trend_state",
    "vix_5d_delta_entry",
    # benchmarking (realized post-entry)
    "iv_rank_entry",
    "iv_percentile_entry",
    "hv_20d_entry",
    "underlying_entry_price",
    "underlying_exit_price",
    "underlying_return",
    "spy_entry_price",
    "spy_exit_price",
    "spy_return_over_window",
    "labeled_at",
}


def _assert_pick_flags_guarded(rows, name):
    """Non-NULL pick flags may only appear on strictly-past entry days (ET)."""
    today = date.today().isoformat()
    for r in rows:
        for flag in ("was_tournament_pick", "was_topscore_pick"):
            if flag in r and r[flag] is not None and str(r.get("entry_day", ""))[:10] >= today:
                _fail(name, f"pick flag {flag} exposed for entry_day {r.get('entry_day')}")


def _fail(name: str, msg: str):
    raise AssertionError(f"{name}: {msg}")


# The three upstream-vendor checks (Polygon live fetch, FMP earnings) need a
# mounted market-data secret. Absent one (e.g. a CI runner with BQ-only ADC),
# they must SKIP, not FAIL — the credential gap is an environment fact, not a
# logic regression. This matcher is deliberately narrow (credential/auth/quota
# signatures only) so a real break still surfaces as a FAIL.
def _is_credential_gap(out) -> bool:
    if not isinstance(out, dict):
        return False
    err = str(out.get("error", "")).lower()
    return any(
        s in err
        for s in (
            "credential not configured",
            "unauthorized",
            "401",
            "rate/daily limit",
            "quota",
        )
    )


def _ok(result, name: str):
    if isinstance(result, dict) and result.get("error"):
        _fail(name, f"tool returned error: {result['error']}")
    if (
        isinstance(result, list)
        and result
        and isinstance(result[0], dict)
        and result[0].get("error")
    ):
        _fail(name, f"tool returned error: {result[0]['error']}")
    return result


# The curated PUBLIC methodology corpus served through get_playbook (the
# wiki-brain). Every slug here must be catalog-listed, fetchable, and — because
# these render through a FREE public tool — free of internal-infra identifiers.
_METHODOLOGY_PAGES = {
    # selection / methodology policy — how the pool is built and why
    "enrichment-definition",
    "bullish-only-hard-gate",
    "tourney-pool-cap-edge-rank",
    "bracket-tournament-selection",
    "gigo-same-day-exit",
    "earnings-exclusion-rail",
    "regime-rail-vix-term",
    "leakage-safety-gate",
    "spread-gate-retired",
    "opportunity-surface",
    # findings (tested on our cohorts)
    "bullish-direction-asymmetry",
    "delta-band-0-20-0-46",
    "option-pnl-not-underlying",
    "fixed-exit-composites-negative",
    "pool-delta-calibrated",
    "path-calibrated-giveback",
    "three-day-harvest-curve",
    "moneyness-10-15-otm",
    "mom-60-conditional-lever",
    "voi-ratio-anti-edge",
    "oi-not-quality-signal",
    "ride-winners-mean-reverts",
    "entry-1000-et",
    # literature
    "earnings-iv-crush",
    "position-sizing-basics",
    # the catalog/index note
    "methodology",
}

# Internal-infra identifiers that must NEVER appear in a public methodology
# page (service names, BQ tables, env vars, model ids, vendors, private doc
# paths, GCP project). Matched case-insensitively as substrings. Public field
# names (overnight_score, mom_60, recommended_*) are intentionally NOT here.
_BANNED_METHODOLOGY_TOKENS = (
    "enrichment-trigger",
    "signal-notifier",
    "signal-judge",
    "overnight_signals_enriched",
    "enriched_option_outcomes",
    "forward_paper_ledger",
    "todays_pick",
    "paper_shadow",
    "paper-shadow",
    "topscore",
    "shadow-tracker",
    "bullish_only",
    "tourney_pool_cap",
    "oi_floor",
    "gemini-3.1",
    "tournament_v1",
    "polygon",
    "financialmodelingprep",
    "bigquery",
    "cloud run",
    "decisions/",
    "findings_ledger",
    "intelligence_brief",
    "profitscout",
)


def run_all() -> list[tuple[str, str]]:
    sys.path.insert(0, "src")

    # V4 surface: the 9 consolidated handlers. Absorbed V3 tools are reached
    # through their view=/granularity= modes.
    from tools.v4 import (
        get_daily_report,
        get_liquidity,
        get_market_calendar_status,
        get_playbook,
        get_pool,
        get_regime_context,
        get_signal,
        query_outcomes,
        replay_contract,
    )

    results: list[tuple[str, str]] = []
    historical_date = (date.today() - timedelta(days=14)).isoformat()

    def check(name, fn, verify=None, expect_error=False, credential_optional=False):
        try:
            out = fn()
            if credential_optional and _is_credential_gap(out):
                results.append((name, "SKIP (no market-data credential in this env)"))
                return
            if not expect_error:
                out = _ok(out, name)
            note = verify(out) if verify else ""
            results.append((name, f"PASS {note}".strip()))
        except AssertionError as e:
            results.append((name, f"FAIL {e}"))
        except Exception as e:  # noqa: BLE001
            results.append((name, f"FAIL {type(e).__name__}: {e}"))

    # --- get_pool: raw | enriched | features | preview ------------------
    check(
        "get_pool[raw]",
        lambda: get_pool(view="raw", limit=5),
        lambda r: f"({len(r)} rows)",
    )

    def _verify_enriched(rows):
        if not rows:
            _fail("get_pool[enriched]", "no rows")
        leaked = FORWARD_OUTCOME_COLS & set(rows[0].keys())
        if leaked:
            _fail("get_pool[enriched]", f"LEAK: forward-outcome cols {leaked}")
        return f"({len(rows)} rows, no forward-outcome cols)"

    check("get_pool[enriched]", lambda: get_pool(limit=5), _verify_enriched)

    # historical-date leak check (the exact V2 leak: outcomes filled on old dates)
    def _scan_dates():
        return [
            d["scan_date"]
            for d in get_market_calendar_status(view="scan_dates")
            if "scan_date" in d
        ]

    def _hist_enriched():
        rows = get_pool(limit=3)
        old = [d for d in _scan_dates() if d <= historical_date]
        target = old[0] if old else rows[0]["scan_date"]
        return get_pool(scan_date=target, limit=3)

    check("get_pool[enriched,historical]", _hist_enriched, _verify_enriched)

    # full-row (summary=False) historical leak check — this is the SELECT *
    # path where the original V2 leak lived; the summary default no longer
    # exercises it, so it needs its own assertion (TF-02 review fix #3).
    def _hist_enriched_full():
        old = [d for d in _scan_dates() if d <= historical_date]
        target = old[0] if old else None
        return get_pool(scan_date=target, limit=3, summary=False)

    def _verify_enriched_full(rows):
        note = _verify_enriched(rows)
        if "is_tradeable" in rows[0]:
            _fail("get_pool[enriched,full]", "TF-15 regression: is_tradeable served")
        return note.replace("no forward-outcome cols", "full rows, no leak, no is_tradeable")

    check("get_pool[enriched,full,historical]", _hist_enriched_full, _verify_enriched_full)

    # fields projection must reject forward-outcome columns (they are absent
    # from the safe view; a request for one returns an error, never data).
    def _fields_reject():
        out = get_pool(limit=3, fields=["next_day_pct", "is_win", "outcome_tier"])
        if not (out and isinstance(out[0], dict) and "error" in out[0]):
            _fail("fields-reject", f"forward-outcome fields not rejected: {out[:1]}")
        return out

    check(
        "get_pool[enriched,fields-reject]",
        _fields_reject,
        lambda r: "(forward-outcome fields rejected)",
        expect_error=True,
    )

    def _detail():
        rows = _ok(get_pool(limit=1), "detail-seed")
        return get_signal(ticker=rows[0]["ticker"], scan_date=rows[0]["scan_date"][:10])

    check(
        "get_signal[detail]",
        _detail,
        lambda r: (
            _fail("get_signal[detail]", f"LEAK: {FORWARD_OUTCOME_COLS & set(r)}")
            if FORWARD_OUTCOME_COLS & set(r)
            else f"({r.get('ticker')})"
        ),
    )
    check(
        "get_pool[preview]", lambda: get_pool(view="preview", limit=3), lambda r: f"({len(r)} rows)"
    )

    # --- substrate ------------------------------------------------------
    def _verify_features(out):
        rows = out["rows"]
        if not rows:
            _fail("get_pool[features]", "no rows")
        bad = NON_FEATURE_COLS & set(rows[0].keys())
        if bad:
            _fail("get_pool[features]", f"LEAK: non-feature cols {bad}")
        _assert_pick_flags_guarded(rows, "get_pool[features]")
        return f"({out['row_count']} rows @ {out['scan_date']}, features only)"

    check("get_pool[features]", lambda: get_pool(view="features", limit=10), _verify_features)

    def _verify_surface(out):
        rows = out["rows"]
        if not rows:
            _fail("query_outcomes[surface]", "no rows")
        open_rows = [r for r in rows if r.get("opp_status") != "OK"]
        if open_rows:
            _fail("query_outcomes[surface]", f"{len(open_rows)} non-closed rows in default mode")
        return f"({out['row_count']} closed-window rows)"

    check(
        "query_outcomes[surface]",
        lambda: query_outcomes(view="surface", days=30),
        _verify_surface,
    )

    def _verify_surface_truncation(out):
        """Row mode must DECLARE the 200-row cap. It used to report only
        row_count, so a days=30 pull silently returned the newest ~4 scan dates
        out of ~17 and, because the sort is peak DESC, the oldest returned date
        contributed only its highest-MFE rows: median MFE inflated 46%."""
        for k in ("matched_rows", "truncated", "partial_scan_date"):
            if k not in out:
                _fail("query_outcomes[surface]", f"missing truncation key {k}")
        if out["matched_rows"] < out["row_count"]:
            _fail("query_outcomes[surface]", "matched_rows < row_count")
        if out["truncated"] != (out["matched_rows"] > out["row_count"]):
            _fail("query_outcomes[surface]", "truncated flag disagrees with counts")
        if out["truncated"] and "TRUNCATED" not in out["meta"]["note"]:
            _fail("query_outcomes[surface]", "truncated response does not say so in its note")
        if any("_matched_rows" in r for r in out["rows"]):
            _fail("query_outcomes[surface]", "internal _matched_rows leaked into rows")
        return f"(matched {out['matched_rows']}, returned {out['row_count']})"

    check(
        "query_outcomes[surface,truncation-disclosed]",
        lambda: query_outcomes(view="surface", days=30),
        _verify_surface_truncation,
    )

    def _verify_surface_agg(out):
        agg, meta = out.get("aggregate") or {}, out.get("meta") or {}
        if not agg or "rows" in out:
            _fail("query_outcomes[surface,agg]", "aggregate_only returned rows or no aggregate")
        # n is the matched population; the statistics rest on n_with_surface.
        # WINDOW_OPEN rows carry NULL in every opp_* VALUE column, so an
        # unguarded COUNT(*) would report an n the quantiles were never fitted
        # to. (opp_window_days / opp_sim_version ARE populated while open.)
        if agg.get("n_with_surface") is None:
            _fail("query_outcomes[surface,agg]", "aggregate omits n_with_surface")
        if agg["n_with_surface"] > agg["n"]:
            _fail("query_outcomes[surface,agg]", "n_with_surface exceeds n")
        if "Not investment advice." not in meta.get("note", ""):
            _fail("query_outcomes[surface,agg]", "aggregate ships without composite disclaimer")
        if not agg.get("opp_sim_versions"):
            _fail("query_outcomes[surface,agg]", "aggregate does not pin opp_sim_version")
        return f"(n={agg['n']} surface={agg['n_with_surface']})"

    check(
        "query_outcomes[surface,aggregate_only]",
        lambda: query_outcomes(view="surface", days=30, aggregate_only=True),
        _verify_surface_agg,
    )

    def _verify_surface_frontier(out):
        """The frontier block must VERIFY liveness, never assert it. A row keeps
        WINDOW_OPEN forever if the fill job stops (the 2026-06-26 stall left 950
        rows open though every window had closed), so the reassuring note is
        only legal when open_past_due == 0."""
        f = (out.get("meta") or {}).get("frontier") or {}
        if f.get("status") == "unavailable":
            return "(frontier unavailable, failed soft)"
        if "open_past_due" not in f:
            _fail("query_outcomes[surface]", "frontier does not check past-due windows")
        if not f.get("status_counts"):
            _fail("query_outcomes[surface]", "frontier lacks full status histogram")
        reassures = "will fill on their own" in (f.get("note") or "")
        if reassures and f.get("open_past_due") != 0:
            _fail("query_outcomes[surface]", "frontier reassures while rows are past due")
        return f"(frontier {f.get('closed_frontier')}, past_due={f.get('open_past_due')})"

    check(
        "query_outcomes[surface,frontier-verified]",
        lambda: query_outcomes(view="surface", days=30, aggregate_only=True),
        _verify_surface_frontier,
    )

    def _verify_surface_delta(out):
        """utils.safety.clamp is int-by-contract, so routing delta bounds
        through it collapses 0.20 to 0 and silently empties the band."""
        agg = out.get("aggregate") or {}
        if not agg.get("n"):
            _fail("query_outcomes[surface,delta]", "delta band matched 0 rows (int-clamp bug?)")
        bad = query_outcomes(view="surface", days=30, delta_min=0.8, delta_max=0.2)
        if not bad.get("error"):
            _fail("query_outcomes[surface,delta]", "inverted delta band was not rejected")
        # excluded_null_delta must be scoped to THIS call's population, not to
        # the bare date window. A ticker-scoped call reporting the whole
        # lookback's NULL-delta total is a disclosure number that is wrong and
        # that reconciles perfectly against itself.
        wide = query_outcomes(
            view="surface", days=30, aggregate_only=True, delta_min=0.20, delta_max=0.46
        )
        narrow = query_outcomes(
            view="surface",
            days=30,
            aggregate_only=True,
            ticker="NVDA",
            delta_min=0.20,
            delta_max=0.46,
        )
        w = (wide.get("meta") or {}).get("excluded_null_delta", 0)
        nrw = (narrow.get("meta") or {}).get("excluded_null_delta", 0)
        # STRICT, and only meaningful when the window actually has NULL deltas.
        # `nrw > w` alone is vacuous: a regression to the date-window-scoped
        # count makes both numbers identical, so the check would pass against
        # the exact defect it names. Equal counts are only legitimate when the
        # population has no NULL deltas at all.
        if w > 0 and nrw >= w:
            _fail(
                "query_outcomes[surface,delta]",
                f"excluded_null_delta ignores the ticker filter (narrow {nrw} >= wide {w})",
            )
        scoped = "n/a (no NULL deltas in window)" if w == 0 else f"{nrw}<{w}"
        return f"(band n={agg['n']}, inverted rejected, null-delta {scoped})"

    check(
        "query_outcomes[surface,delta-band]",
        lambda: query_outcomes(
            view="surface", days=30, aggregate_only=True, delta_min=0.20, delta_max=0.46
        ),
        _verify_surface_delta,
    )

    def _verify_outcomes(out):
        rows = out["rows"]
        if not rows:
            _fail("query_outcomes[labels]", "no rows")
        if any(r.get("realized_return_pct") is None for r in rows):
            _fail("query_outcomes[labels]", "NULL label row leaked through default filter")
        if any(r.get("illiquid_exit") for r in rows):
            _fail("query_outcomes[labels]", "illiquid row leaked through default filter")
        if "realized_return_pct_3d" in rows[0]:
            _fail("query_outcomes[labels]", "3d label mixed into same_day horizon")
        for r in rows:
            if r.get("opp_status") != "OK" and (
                r.get("opp_peak_return") is not None or r.get("opp_trough_return") is not None
            ):
                _fail("query_outcomes[labels]", "open-window opp excursion leaked")
        _assert_pick_flags_guarded(rows, "query_outcomes[labels]")
        meta = out["meta"]
        return f"({out['row_count']} rows; excl null={meta['excluded_null_label']} illiq={meta['excluded_illiquid']})"

    check(
        "query_outcomes[labels,same_day]",
        lambda: query_outcomes(
            view="labels", horizon="same_day", delta_min=0.2, delta_max=0.46, limit=20
        ),
        _verify_outcomes,
    )
    check(
        "query_outcomes[labels,3d]",
        lambda: query_outcomes(view="labels", horizon="3d", limit=10),
        lambda out: (
            _fail("query_outcomes[labels,3d]", "same-day label mixed into 3d horizon")
            if out["rows"] and "realized_return_pct" in out["rows"][0]
            else f"({out['row_count']} rows)"
        ),
    )
    check(
        "query_outcomes[summary]",
        lambda: query_outcomes(view="summary", horizon="3d", group_by="delta_bucket"),
        lambda out: f"({len(out['groups'])} groups; disclaimer={'disclaimer' in out['meta']})",
    )
    check(
        "query_outcomes[summary,bad-group]",
        lambda: query_outcomes(view="summary", group_by="ticker; DROP TABLE x"),
        lambda out: (
            "(rejected non-whitelisted group_by)"
            if out.get("error")
            else _fail("query_outcomes[summary]", "accepted non-whitelisted group_by!")
        ),
        expect_error=True,
    )

    def _verify_exit(out):
        if out.get("n_classified", 0) <= 0:
            _fail("query_outcomes[exit_rule]", "no classified rows")
        buckets = set(out["buckets"].keys())
        if "AMBIGUOUS" in buckets:
            _fail(
                "query_outcomes[exit_rule]", "AMBIGUOUS bucket present — should be resolved+tagged"
            )
        return (
            f"(n={out['n_classified']}, wr~{out['est_win_rate']}, "
            f"heuristic={out['heuristic_share']}, ev=[{out['ev_bounds']['low']},{out['ev_bounds']['high']}])"
        )

    check(
        "query_outcomes[exit_rule]",
        lambda: query_outcomes(view="exit_rule", target_pct=40, stop_pct=-30, horizon="3d"),
        _verify_exit,
    )
    check(
        "query_outcomes[exit_rule,exact-3d]",
        lambda: query_outcomes(view="exit_rule", target_pct=80, stop_pct=60, horizon="3d"),
        lambda out: (
            f"(exact n={out['exact_label_match']['n']}, wr={out['exact_label_match']['win_rate']})"
            if out.get("exact_label_match")
            else _fail(
                "query_outcomes[exit_rule]", "exact 3d rule did not return exact_label_match"
            )
        ),
    )
    check(
        "get_regime_context",
        get_regime_context,
        lambda r: (
            f"({r['scan_date']} vix={r['vix_at_scan']} rail={r['regime_rail_pass']}, lag noted)"
            if r.get("latest_available_scan_date")
            else _fail("get_regime_context", "TF-07: latest_available_scan_date missing")
        ),
    )

    # --- wave-2 additions (2026-07-06) -------------------------------------
    def _verify_harvest(r):
        ps = [t["p_touch"] for t in r["targets"]]
        if ps != sorted(ps, reverse=True):
            _fail("query_outcomes[harvest]", f"p_touch not monotone in target: {ps}")
        if not all(0.0 <= p <= 1.0 for p in ps):
            _fail("query_outcomes[harvest]", "p_touch out of [0,1]")
        if "rows" in r:
            _fail("query_outcomes[harvest]", "row-level data leaked from an aggregate tool")
        return f"(n={r['n']}, p20={r['targets'][1]['p_touch']}, aggregates only)"

    check(
        "query_outcomes[harvest]",
        lambda: query_outcomes(view="harvest", targets=[15, 20, 50, 100]),
        _verify_harvest,
    )
    check(
        "query_outcomes[summary,moneyness]",
        lambda: query_outcomes(view="summary", horizon="3d", group_by="moneyness_bucket"),
        lambda r: (
            f"({len(r['groups'])} moneyness buckets)"
            if r.get("groups")
            else _fail("query_outcomes[summary]", "moneyness_bucket returned no groups")
        ),
    )
    check(
        "query_outcomes[labels,aggregate_only]",
        lambda: query_outcomes(view="labels", horizon="3d", aggregate_only=True),
        lambda r: (
            f"(agg n={r['aggregate'].get('n')}, no rows key={'rows' not in r})"
            if r.get("aggregate") and "rows" not in r
            else _fail("query_outcomes[labels]", "aggregate_only returned rows or no aggregate")
        ),
    )
    check(
        "get_pool[features,empty-date]",
        lambda: get_pool(view="features", scan_date="2020-01-02"),
        lambda r: (
            "(0 rows + latest_labeled pointer)"
            if r.get("row_count") == 0 and r.get("latest_labeled_scan_date")
            else _fail("get_pool[features]", "TF-06: empty date lacks latest_labeled pointer")
        ),
    )
    check(
        "get_signal[detail,not-in-pool]",
        lambda: get_signal(ticker="ZZZZZZ"),
        lambda r: (
            "(friendly not-in-pool error)"
            if r.get("error") and r.get("note")
            else _fail("get_signal[detail]", "Q3: no friendly not-in-pool message")
        ),
        expect_error=True,
    )

    def _snapshot_check():
        rows = _ok(get_pool(limit=1), "snapshot-seed")
        return get_liquidity(contract=rows[0]["recommended_contract"])

    check(
        "get_liquidity[contract]",
        _snapshot_check,
        lambda r: (
            _fail(
                "get_liquidity[contract]",
                f"quote field leaked: {set(r) & {'bid', 'ask', 'spread_pct', 'mid'}}",
            )
            if set(r) & {"bid", "ask", "spread_pct", "mid"}
            else f"(oi={r.get('open_interest')}, vol={r.get('day_volume')}, as_of={str(r.get('as_of'))[:16]})"
        ),
        credential_optional=True,
    )
    check(
        "get_liquidity[contract,bad-input]",
        lambda: get_liquidity(contract="'; DROP TABLE--"),
        lambda r: (
            "(rejected malformed contract)"
            if r.get("error")
            else _fail("get_liquidity[contract]", "malformed contract accepted!")
        ),
        expect_error=True,
    )

    # --- Priority-1 (2026-07-07): cache-first + live + batch + TF-18 ---------
    _P1_PROVENANCE = {"pool_liquidity_cache", "pool_liquidity_cache_stale", "upstream_live"}

    def _snapshot_p1_check():
        rows = _ok(get_pool(limit=1), "snapshot-seed")
        return get_liquidity(contract=rows[0]["recommended_contract"])

    check(
        "get_liquidity[contract,provenance+TF-18]",
        _snapshot_p1_check,
        lambda r: (
            f"(from={r.get('retrieved_from')}, und_px={r.get('underlying_price')} "
            f"[{r.get('underlying_price_source')}])"
            if r.get("retrieved_from") in _P1_PROVENANCE and r.get("underlying_price")
            else _fail(
                "get_liquidity[contract]",
                f"P1 regression: retrieved_from={r.get('retrieved_from')}, "
                f"underlying_price={r.get('underlying_price')}",
            )
        ),
        credential_optional=True,
    )

    def _snapshot_live_check():
        rows = _ok(get_pool(limit=1), "snapshot-seed")
        return get_liquidity(contract=rows[0]["recommended_contract"], live=True)

    check(
        "get_liquidity[contract,live=true]",
        _snapshot_live_check,
        lambda r: (
            f"(upstream_live, as_of={str(r.get('as_of'))[:16]})"
            if r.get("retrieved_from") == "upstream_live"
            else _fail(
                "get_liquidity[contract]", f"live=true not upstream: {r.get('retrieved_from')}"
            )
        ),
        credential_optional=True,
    )

    def _pool_liquidity_verify(r):
        if not r.get("rows"):
            # legitimate off-hours/holiday emptiness only if honestly noted
            return (
                "(0 rows + note)"
                if r.get("note")
                else _fail("get_liquidity[pool]", "empty without note")
            )
        leaked = [row for row in r["rows"] if set(row) & {"bid", "ask", "spread_pct", "mid"}]
        if leaked:
            _fail("get_liquidity[pool]", f"NULL quote fields leaked on {len(leaked)} rows")
        missing_asof = [row for row in r["rows"] if not row.get("as_of")]
        if missing_asof:
            _fail("get_liquidity[pool]", f"{len(missing_asof)} rows missing as_of provenance")
        return f"({r['count']} rows, scan_date={r.get('scan_date')}, freshest={str(r.get('freshest_as_of'))[:16]})"

    check("get_liquidity[pool]", get_liquidity, _pool_liquidity_verify)

    def _pool_liquidity_shortlist():
        pool = _ok(get_liquidity(), "pool-liq-seed")
        if not pool.get("rows"):
            return {"skipped": True, "note": "no snapshots yet today"}
        shortlist = [row["contract"] for row in pool["rows"][:3]]
        return get_liquidity(contracts=shortlist)

    check(
        "get_liquidity[pool,shortlist]",
        _pool_liquidity_shortlist,
        lambda r: (
            "(skipped: no snapshots)"
            if r.get("skipped")
            else (
                f"({r['count']} rows in one call)"
                if 0 < r.get("count", 0) <= 3
                else _fail("get_liquidity[pool]", f"shortlist returned {r.get('count')}")
            )
        ),
    )
    check(
        "get_liquidity[pool,bad-contract]",
        lambda: get_liquidity(contracts=["'; DROP TABLE--"]),
        lambda r: (
            "(rejected malformed contract)"
            if r.get("error")
            else _fail("get_liquidity[pool]", "malformed contract accepted!")
        ),
        expect_error=True,
    )

    # --- RM-003 (2026-07-07): earnings window (get_signal view=earnings) -----
    def _earnings_check():
        rows = _ok(get_pool(limit=1), "earnings-seed")
        return get_signal(view="earnings", contract=rows[0]["recommended_contract"])

    def _verify_earnings(r):
        if r.get("earnings_in_window") is None:
            # unknown is legitimate ONLY with the explicit fail-closed guidance
            blob = (str(r.get("note", "")) + str(r.get("error", ""))).lower()
            if "in-window" not in blob:
                _fail("get_signal[earnings]", "unknown date without fail-closed note")
            return f"(unknown -> fail-closed noted, ticker={r.get('ticker')})"
        if not r.get("expiration") or not r.get("next_earnings_date"):
            _fail("get_signal[earnings]", "resolved window missing expiration/date")
        return (
            f"({r['ticker']}: next={r['next_earnings_date']} exp={r['expiration']} "
            f"in_window={r['earnings_in_window']})"
        )

    check(
        "get_signal[earnings,contract]", _earnings_check, _verify_earnings, credential_optional=True
    )
    check(
        "get_signal[earnings,bad-ticker]",
        lambda: get_signal(view="earnings", ticker="'; DROP--"),
        lambda r: (
            "(rejected malformed ticker)"
            if r.get("error")
            else _fail("get_signal[earnings]", "malformed ticker accepted!")
        ),
        expect_error=True,
    )

    # --- RM-004 data (2026-07-07): daily marks (replay_contract gran=day) ----
    def _marks_check():
        rows = _ok(get_pool(limit=1), "marks-seed")
        return replay_contract(rows[0]["recommended_contract"], granularity="day")

    def _verify_marks(r):
        if r.get("bar_count", 0) < 1:
            # a brand-new contract can be legitimately bar-less — but only with
            # the honest empty-window note
            if "No bars" not in str(r.get("note", "")):
                _fail("replay_contract[day]", "empty series without honest note")
            return "(0 bars + honest note)"
        b = r["bars"][0]
        for k in ("date", "close"):
            if b.get(k) is None:
                _fail("replay_contract[day]", f"bar missing {k}")
        if "exit" in str(r.get("note", "")).lower() and "not simulate" not in str(
            r.get("note", "")
        ):
            _fail("replay_contract[day]", "boundary note drifted")
        return f"({r['bar_count']} daily bars {r['from_date']}..{r['to_date']})"

    check("replay_contract[day]", _marks_check, _verify_marks, credential_optional=True)
    check(
        "replay_contract[day,bad-input]",
        lambda: replay_contract("SPY", granularity="day"),
        lambda r: (
            "(rejected non-OCC ticker)"
            if r.get("error")
            else _fail("replay_contract[day]", "non-OCC ticker accepted!")
        ),
        expect_error=True,
    )
    check(
        "replay_contract[day,bad-date]",
        lambda: replay_contract("O:AAPL260717C00315000", granularity="day", from_date="2026-02-30"),
        lambda r: (
            "(rejected impossible date)"
            if r.get("error") and "real" in r["error"]
            else _fail("replay_contract[day]", "impossible date accepted/raised")
        ),
        expect_error=True,
    )
    check(
        "replay_contract[day,span-cap]",
        lambda: replay_contract(
            "O:AAPL260717C00315000",
            granularity="day",
            from_date="2025-01-01",
            to_date="2026-07-01",
        ),
        lambda r: (
            "(rejected over-cap span)"
            if r.get("error") and "capped" in r["error"]
            else _fail("replay_contract[day]", "over-cap span accepted!")
        ),
        expect_error=True,
    )

    # --- RM-002 + TF-14 (2026-07-07): minute replay + trailing scoring -------
    def _replay_check():
        # seed from the labeled substrate so the minute-path table has the row
        feats = _ok(get_pool(view="features", limit=1), "replay-seed")
        row = feats["rows"][0] if isinstance(feats, dict) else feats[0]
        return replay_contract(
            row["recommended_contract"],
            date=str(row["entry_day"])[:10],
            target_pct=40,
            stop_pct=30,
        )

    def _verify_replay(r):
        if r.get("bar_count", 0) < 1:
            return (
                "(0 bars + honest note)"
                if "No bars" in str(r.get("note", ""))
                else _fail("replay_contract[minute]", "empty replay without honest note")
            )
        if not r.get("anchor") or not r["anchor"].get("price"):
            _fail("replay_contract[minute]", "missing 10:00 ET anchor")
        fc = r.get("first_crossing") or {}
        if fc.get("first") not in ("TARGET", "STOP", "AMBIGUOUS_SAME_BAR", "NONE"):
            _fail("replay_contract[minute]", f"bad first_crossing verdict: {fc.get('first')}")
        return (
            f"({r['bar_count']} bars from {r['retrieved_from']}, first_crossing={fc.get('first')})"
        )

    check("replay_contract[minute]", _replay_check, _verify_replay)
    check(
        "replay_contract[minute,bad-date]",
        lambda: replay_contract("O:AAPL260717C00315000", date="2026-02-30"),
        lambda r: (
            "(rejected impossible date)"
            if r.get("error")
            else _fail("replay_contract[minute]", "impossible date accepted")
        ),
        expect_error=True,
    )

    def _verify_trailing(r):
        if r.get("n_scored", 0) < 100:
            _fail("query_outcomes[exit_rule,trailing]", f"n_scored={r.get('n_scored')}")
        if r.get("params", {}).get("rule") != "trailing":
            _fail("query_outcomes[exit_rule,trailing]", "params.rule missing")
        if "not exit advice" not in str(r.get("meta", {}).get("research_only", "")):
            _fail("query_outcomes[exit_rule,trailing]", "research-only framing missing")
        return (
            f"(n={r['n_scored']}, wr={r['est_win_rate']}, avg={r['avg_return']}, "
            f"stop_share={r['stop_share']})"
        )

    check(
        "query_outcomes[exit_rule,trailing]",
        lambda: query_outcomes(
            view="exit_rule", stop_pct=30, rule="trailing", trail_pct=25, activation_pct=20
        ),
        _verify_trailing,
    )
    check(
        "query_outcomes[exit_rule,exact-crossing]",
        lambda: query_outcomes(view="exit_rule", target_pct=40, stop_pct=30),
        lambda r: (
            f"(heuristic_share={r['heuristic_share']}, exact={r['exact_resolution']['resolved_by_minute_tape']})"
            if r.get("heuristic_share", 1) <= 0.02 and r.get("exact_resolution")
            else _fail(
                "query_outcomes[exit_rule]",
                f"TF-14 regression: heuristic_share={r.get('heuristic_share')}",
            )
        ),
    )
    check(
        "query_outcomes[exit_rule,trailing-missing-param]",
        lambda: query_outcomes(view="exit_rule", rule="trailing"),
        lambda r: (
            "(rejected missing trail_pct)"
            if r.get("error")
            else _fail("query_outcomes[exit_rule]", "trailing without trail_pct accepted")
        ),
        expect_error=True,
    )

    # --- playbooks (get_playbook: list | name | field | schema) ------------
    check(
        "get_playbook[list]",
        get_playbook,
        lambda r: (
            f"({len(r['playbooks'])} playbooks)"
            if len(r.get("playbooks", [])) >= 6
            else _fail("get_playbook[list]", f"only {len(r.get('playbooks', []))}")
        ),
    )
    check(
        "get_playbook[name]",
        lambda: get_playbook(name="start-here"),
        lambda r: f"({r['title'][:30]}...)",
    )
    check(
        "get_playbook[name,traversal]",
        lambda: get_playbook(name="../../pyproject"),
        lambda r: (
            "(rejected bad name)"
            if r.get("error")
            else _fail("get_playbook[name]", "path traversal accepted!")
        ),
        expect_error=True,
    )

    # --- wiki-brain: the curated methodology corpus is catalog-listed ------
    def _verify_methodology_catalog(out):
        listed = {p.get("name") for p in out.get("playbooks", [])}
        missing = _METHODOLOGY_PAGES - listed
        if missing:
            _fail("get_playbook[methodology,catalog]", f"not in catalog: {sorted(missing)}")
        return f"({len(_METHODOLOGY_PAGES)} methodology pages listed, {len(listed)} total)"

    check("get_playbook[methodology,catalog]", get_playbook, _verify_methodology_catalog)

    # every methodology page fetches with real content AND is scrubbed of
    # internal-infra identifiers (it renders through a FREE public tool).
    def _verify_methodology_pages(_):
        for slug in sorted(_METHODOLOGY_PAGES):
            page = get_playbook(name=slug)
            if page.get("error") or not (page.get("content") or "").strip():
                _fail("get_playbook[methodology,fetch]", f"{slug}: empty/error")
            body = page["content"].lower()
            hit = [t for t in _BANNED_METHODOLOGY_TOKENS if t in body]
            if hit:
                _fail("get_playbook[methodology,scrub]", f"{slug} leaks {hit}")
        return f"({len(_METHODOLOGY_PAGES)} pages fetched + scrubbed clean)"

    check("get_playbook[methodology,fetch+scrub]", lambda: None, _verify_methodology_pages)

    # index note must resolve the two representative slugs it advertises
    check(
        "get_playbook[methodology,index]",
        lambda: get_playbook(name="methodology"),
        lambda r: (
            "(index lists selection + findings)"
            if "bracket-tournament-selection" in r.get("content", "")
            and "fixed-exit-composites-negative" in r.get("content", "")
            else _fail("get_playbook[methodology,index]", "index missing corpus links")
        ),
    )

    # --- performance / receipts (query_outcomes receipts views) ------------
    check(
        "query_outcomes[signal_performance]",
        lambda: query_outcomes(view="signal_performance", limit=5),
        lambda r: (
            f"({r['row_count']} rows, universe={r['universe']})"
            if r.get("universe") == "underlying_direction"
            else _fail("query_outcomes[signal_performance]", "missing universe marker")
        ),
    )
    check(
        "query_outcomes[win_rate]",
        lambda: query_outcomes(view="win_rate", days=30),
        lambda r: f"(wr={r.get('underlying_direction_win_rate')}%, universe={r.get('universe')})",
    )

    def _verify_positions(out):
        today = date.today().isoformat()
        for r in out["rows"]:
            if r["exit_timestamp"][:10] >= today:
                _fail(
                    "query_outcomes[positions]", f"non-realized row leaked: {r['exit_timestamp']}"
                )
            # NOTE: as a COHORT guard this assertion is vacuous — disowned
            # cohorts carry the same policy label, which is how the pre-2026-08-07
            # leak went unnoticed here. Real cohort cover (entry-date floor) lives
            # in tests/test_cohort_filter.py. Kept as a cheap label smoke check.
            if r["policy_version"] != LIVE_POLICY_VERSION:
                _fail("query_outcomes[positions]", f"cohort mix: {r['policy_version']}")
        if "skip_days" not in out:
            _fail("query_outcomes[positions]", "skip_days missing from response")
        return (
            f"({out['row_count']} realized rows, {len(out['skip_days'])} skip days, cohort clean)"
        )

    check(
        "query_outcomes[positions]",
        lambda: query_outcomes(view="positions", days=30),
        _verify_positions,
    )
    check(
        "query_outcomes[performance]",
        lambda: query_outcomes(view="performance", days=30),
        lambda r: f"(n={r['total_trades']} wr={r['win_rate']})",
    )

    # --- reports & metadata ------------------------------------------------
    check(
        "get_daily_report[report]", get_daily_report, lambda r: f"({str(r.get('title'))[:30]}...)"
    )
    check(
        "get_daily_report[list]",
        lambda: get_daily_report(view="list", limit=3),
        lambda r: f"({len(r)} reports)",
    )
    check(
        "get_market_calendar_status[scan_dates]",
        lambda: get_market_calendar_status(view="scan_dates"),
        lambda r: f"({len(r)} dates)",
    )

    def _verify_schema(out):
        classes = {c["classification"] for c in out["columns"]}
        expected = {"feature", "label", "opportunity", "regime_telemetry", "identity"}
        if not expected.issubset(classes):
            _fail("get_playbook[schema]", f"missing classifications: {expected - classes}")
        untagged = [c["column"] for c in out["columns"] if c["classification"] == "untagged"]
        return f"({len(out['columns'])} cols, {len(out['features_view_columns'])} in view, untagged={len(untagged)})"

    check("get_playbook[schema]", lambda: get_playbook(name="schema"), _verify_schema)

    # --- reference -----------------------------------------------------------
    check(
        "get_market_calendar_status[status]",
        get_market_calendar_status,
        lambda r: f"(open={r.get('is_open_today')})",
    )
    check(
        "get_playbook[field]",
        lambda: get_playbook(field="mom_60"),
        lambda r: (
            "(mom_60 explained)"
            if r.get("definition") and "momentum" in r["definition"].lower()
            else _fail("get_playbook[field]", "mom_60 not explained")
        ),
    )

    return results


def test_v3_surface():
    results = run_all()
    failures = [f"{n}: {s}" for n, s in results if s.startswith("FAIL")]
    assert not failures, "\n".join(failures)


if __name__ == "__main__":
    results = run_all()
    width = max(len(n) for n, _ in results)
    fails = skips = 0
    for name, status in results:
        print(f"{name:<{width}}  {status}")
        fails += status.startswith("FAIL")
        skips += status.startswith("SKIP")
    print(
        f"\n{len(results) - fails - skips}/{len(results)} passed, {skips} skipped, {fails} failed"
    )
    sys.exit(1 if fails else 0)
