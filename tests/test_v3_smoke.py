"""
V3 surface smoke test — calls every registered tool against live data and
asserts the leakage guarantees. Runnable directly:

    PYTHONPATH=src .venv/bin/python tests/test_v3_smoke.py

or via pytest. Requires ADC with BigQuery read access.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta

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


def run_all() -> list[tuple[str, str]]:
    sys.path.insert(0, "src")

    from tools.education import get_market_calendar_status, get_signal_explainer
    from tools.historical import get_historical_performance
    from tools.metadata import get_available_dates, get_enriched_signal_schema
    from tools.overnight_signals import (
        get_enriched_signals,
        get_freemium_preview,
        get_overnight_signals,
        get_signal_detail,
    )
    from tools.performance_tracker import (
        get_position_history,
        get_signal_performance,
        get_win_rate_summary,
    )
    from tools.playbooks import get_playbook, list_playbooks
    from tools.reports import get_daily_report, get_report_list
    from tools.substrate import (
        estimate_exit_rule,
        get_opportunity_surface,
        get_outcome_summary,
        get_pool_features,
        get_regime_context,
        query_outcomes,
    )

    results: list[tuple[str, str]] = []
    historical_date = (date.today() - timedelta(days=14)).isoformat()

    def check(name, fn, verify=None, expect_error=False):
        try:
            out = fn()
            if not expect_error:
                out = _ok(out, name)
            note = verify(out) if verify else ""
            results.append((name, f"PASS {note}".strip()))
        except AssertionError as e:
            results.append((name, f"FAIL {e}"))
        except Exception as e:  # noqa: BLE001
            results.append((name, f"FAIL {type(e).__name__}: {e}"))

    # --- live pool -----------------------------------------------------
    check(
        "get_overnight_signals",
        lambda: get_overnight_signals(limit=5),
        lambda r: f"({len(r)} rows)",
    )

    def _verify_enriched(rows):
        if not rows:
            _fail("get_enriched_signals", "no rows")
        leaked = FORWARD_OUTCOME_COLS & set(rows[0].keys())
        if leaked:
            _fail("get_enriched_signals", f"LEAK: forward-outcome cols {leaked}")
        return f"({len(rows)} rows, no forward-outcome cols)"

    check("get_enriched_signals", lambda: get_enriched_signals(limit=5), _verify_enriched)

    # historical-date leak check (the exact V2 leak: outcomes filled on old dates)
    def _hist_enriched():
        rows = get_enriched_signals(limit=3)
        # walk back to a date that has data
        dates = [d["scan_date"] for d in get_available_dates() if "scan_date" in d]
        old = [d for d in dates if d <= historical_date]
        target = old[0] if old else rows[0]["scan_date"]
        return get_enriched_signals(scan_date=target, limit=3)

    check("get_enriched_signals[historical]", _hist_enriched, _verify_enriched)

    def _detail():
        rows = _ok(get_enriched_signals(limit=1), "detail-seed")
        return get_signal_detail(rows[0]["ticker"], rows[0]["scan_date"][:10])

    check(
        "get_signal_detail",
        _detail,
        lambda r: (
            _fail("get_signal_detail", f"LEAK: {FORWARD_OUTCOME_COLS & set(r)}")
            if FORWARD_OUTCOME_COLS & set(r)
            else f"({r.get('ticker')})"
        ),
    )
    check(
        "get_freemium_preview", lambda: get_freemium_preview(limit=3), lambda r: f"({len(r)} rows)"
    )

    # --- substrate ------------------------------------------------------
    def _verify_features(out):
        rows = out["rows"]
        if not rows:
            _fail("get_pool_features", "no rows")
        bad = NON_FEATURE_COLS & set(rows[0].keys())
        if bad:
            _fail("get_pool_features", f"LEAK: non-feature cols {bad}")
        _assert_pick_flags_guarded(rows, "get_pool_features")
        return f"({out['row_count']} rows @ {out['scan_date']}, features only)"

    check("get_pool_features", lambda: get_pool_features(limit=10), _verify_features)

    def _verify_surface(out):
        rows = out["rows"]
        if not rows:
            _fail("get_opportunity_surface", "no rows")
        open_rows = [r for r in rows if r.get("opp_status") != "OK"]
        if open_rows:
            _fail("get_opportunity_surface", f"{len(open_rows)} non-closed rows in default mode")
        return f"({out['row_count']} closed-window rows)"

    check("get_opportunity_surface", lambda: get_opportunity_surface(days=30), _verify_surface)

    def _verify_outcomes(out):
        rows = out["rows"]
        if not rows:
            _fail("query_outcomes", "no rows")
        if any(r.get("realized_return_pct") is None for r in rows):
            _fail("query_outcomes", "NULL label row leaked through default filter")
        if any(r.get("illiquid_exit") for r in rows):
            _fail("query_outcomes", "illiquid row leaked through default filter")
        if "realized_return_pct_3d" in rows[0]:
            _fail("query_outcomes", "3d label mixed into same_day horizon")
        for r in rows:
            if r.get("opp_status") != "OK" and (
                r.get("opp_peak_return") is not None or r.get("opp_trough_return") is not None
            ):
                _fail("query_outcomes", "open-window opp excursion leaked")
        _assert_pick_flags_guarded(rows, "query_outcomes")
        meta = out["meta"]
        return f"({out['row_count']} rows; excl null={meta['excluded_null_label']} illiq={meta['excluded_illiquid']})"

    check(
        "query_outcomes[same_day]",
        lambda: query_outcomes(horizon="same_day", delta_min=0.2, delta_max=0.46, limit=20),
        _verify_outcomes,
    )
    check(
        "query_outcomes[3d]",
        lambda: query_outcomes(horizon="3d", limit=10),
        lambda out: (
            _fail("query_outcomes[3d]", "same-day label mixed into 3d horizon")
            if out["rows"] and "realized_return_pct" in out["rows"][0]
            else f"({out['row_count']} rows)"
        ),
    )
    check(
        "get_outcome_summary",
        lambda: get_outcome_summary(horizon="3d", group_by="delta_bucket"),
        lambda out: f"({len(out['groups'])} groups; disclaimer={'disclaimer' in out['meta']})",
    )
    check(
        "get_outcome_summary[bad-group]",
        lambda: get_outcome_summary(group_by="ticker; DROP TABLE x"),
        lambda out: (
            "(rejected non-whitelisted group_by)"
            if out.get("error")
            else _fail("get_outcome_summary", "accepted non-whitelisted group_by!")
        ),
        expect_error=True,
    )

    def _verify_exit(out):
        if out.get("n_classified", 0) <= 0:
            _fail("estimate_exit_rule", "no classified rows")
        buckets = set(out["buckets"].keys())
        if "AMBIGUOUS" in buckets:
            _fail("estimate_exit_rule", "AMBIGUOUS bucket present — should be resolved+tagged")
        return (
            f"(n={out['n_classified']}, wr~{out['est_win_rate']}, "
            f"heuristic={out['heuristic_share']}, ev=[{out['ev_bounds']['low']},{out['ev_bounds']['high']}])"
        )

    check("estimate_exit_rule", lambda: estimate_exit_rule(40, -30, horizon="3d"), _verify_exit)
    check(
        "estimate_exit_rule[exact-3d]",
        lambda: estimate_exit_rule(80, 60, horizon="3d"),
        lambda out: (
            f"(exact n={out['exact_label_match']['n']}, wr={out['exact_label_match']['win_rate']})"
            if out.get("exact_label_match")
            else _fail("estimate_exit_rule", "exact 3d rule did not return exact_label_match")
        ),
    )
    check(
        "get_regime_context",
        get_regime_context,
        lambda r: f"({r['scan_date']} vix={r['vix_at_scan']} rail={r['regime_rail_pass']})",
    )

    # --- playbooks --------------------------------------------------------
    check(
        "list_playbooks",
        list_playbooks,
        lambda r: (
            f"({len(r)} playbooks)" if len(r) >= 6 else _fail("list_playbooks", f"only {len(r)}")
        ),
    )
    check(
        "get_playbook",
        lambda: get_playbook("start-here"),
        lambda r: f"({r['title'][:30]}...)",
    )
    check(
        "get_playbook[traversal]",
        lambda: get_playbook("../../pyproject"),
        lambda r: (
            "(rejected bad name)"
            if r.get("error")
            else _fail("get_playbook", "path traversal accepted!")
        ),
        expect_error=True,
    )

    # --- performance / receipts -------------------------------------------
    check(
        "get_signal_performance",
        lambda: get_signal_performance(limit=5),
        lambda r: (
            f"({r['row_count']} rows, universe={r['universe']})"
            if r.get("universe") == "underlying_direction"
            else _fail("get_signal_performance", "missing universe marker")
        ),
    )
    check(
        "get_win_rate_summary",
        lambda: get_win_rate_summary(days=30),
        lambda r: f"(wr={r.get('underlying_direction_win_rate')}%, universe={r.get('universe')})",
    )

    def _verify_positions(out):
        today = date.today().isoformat()
        for r in out["rows"]:
            if r["exit_timestamp"][:10] >= today:
                _fail("get_position_history", f"non-realized row leaked: {r['exit_timestamp']}")
            if r["policy_version"] != "V7_1_TILTED_GIGO":
                _fail("get_position_history", f"cohort mix: {r['policy_version']}")
        if "skip_days" not in out:
            _fail("get_position_history", "skip_days missing from response")
        return (
            f"({out['row_count']} realized rows, {len(out['skip_days'])} skip days, cohort clean)"
        )

    check("get_position_history", lambda: get_position_history(days=30), _verify_positions)
    check(
        "get_historical_performance",
        lambda: get_historical_performance(lookback_days=30),
        lambda r: f"(n={r['total_trades']} wr={r['win_rate']})",
    )

    # --- reports & metadata ------------------------------------------------
    check("get_daily_report", get_daily_report, lambda r: f"({str(r.get('title'))[:30]}...)")
    check("get_report_list", lambda: get_report_list(limit=3), lambda r: f"({len(r)} reports)")
    check("get_available_dates", get_available_dates, lambda r: f"({len(r)} dates)")

    def _verify_schema(out):
        classes = {c["classification"] for c in out["columns"]}
        expected = {"feature", "label", "opportunity", "regime_telemetry", "identity"}
        if not expected.issubset(classes):
            _fail("get_enriched_signal_schema", f"missing classifications: {expected - classes}")
        untagged = [c["column"] for c in out["columns"] if c["classification"] == "untagged"]
        return f"({len(out['columns'])} cols, {len(out['features_view_columns'])} in view, untagged={len(untagged)})"

    check("get_enriched_signal_schema", get_enriched_signal_schema, _verify_schema)

    # --- reference -----------------------------------------------------------
    check(
        "get_market_calendar_status",
        get_market_calendar_status,
        lambda r: f"(open={r.get('is_open_now')})",
    )
    check(
        "get_signal_explainer",
        lambda: get_signal_explainer("mom_60"),
        lambda r: (
            "(mom_60 explained)"
            if r.get("definition") and "momentum" in r["definition"].lower()
            else _fail("get_signal_explainer", "mom_60 not explained")
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
    fails = 0
    for name, status in results:
        print(f"{name:<{width}}  {status}")
        if status.startswith("FAIL"):
            fails += 1
    print(f"\n{len(results) - fails}/{len(results)} passed")
    sys.exit(1 if fails else 0)
