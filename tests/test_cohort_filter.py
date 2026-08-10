"""Live-cohort filter tests (2026-08-07).

Regression cover for the defect where the MCP defined the live cohort by
`policy_version` ALONE. Since 2026-07-28 the engine's cohort resets are
DATE-FILTER resets, not truncations, so disowned cohorts stay in
`forward_paper_ledger` under the same label — and this server served them as
live receipts for ~10 days, including two picks the engine had established were
selected on a phantom liquidity count.

The existing v3 smoke test cannot catch this: it asserts
`row["policy_version"] == "V7_1_TILTED_GIGO"` over returned rows, which is
vacuously true both when the filter is correct AND when it wrongly returns
disowned rows carrying that same label.

These tests hit real BigQuery (read-only), consistent with the rest of tests/.

    PYTHONPATH=src .venv/bin/python -m pytest tests/test_cohort_filter.py -q
"""

from __future__ import annotations

import datetime as _dt

import pytest

from tools.historical import get_historical_performance
from tools.performance_tracker import get_position_history
from utils.data import (
    DISOWNED_COHORT_NOTE,
    LIVE_COHORT_START_DATE,
    LIVE_POLICY_VERSION,
)

_STAT_KEYS = ("win_rate", "avg_return", "median_return", "best", "worst")

LOOKBACK = 120  # wide enough to span several cohorts


def _iso_to_date(s: str) -> _dt.date:
    return _dt.date.fromisoformat(s[:10])


def test_cohort_start_is_a_valid_date_and_pairs_with_the_label():
    """The cohort is a (label, start date) PAIR. Both must exist."""
    assert LIVE_POLICY_VERSION == "V7_1_TILTED_GIGO"
    d = _iso_to_date(LIVE_COHORT_START_DATE)
    assert d.year >= 2026


def test_positions_live_cohort_never_returns_pre_cohort_rows():
    """THE regression. Every returned receipt must have entered on/after the
    cohort start — a label match alone is not sufficient."""
    out = get_position_history(days=LOOKBACK)
    assert "error" not in out, out
    assert out.get("cohort_start") == LIVE_COHORT_START_DATE
    floor = _iso_to_date(LIVE_COHORT_START_DATE)
    for r in out.get("rows", []):
        assert r["policy_version"] == LIVE_POLICY_VERSION
        entered = _iso_to_date(r["entry_timestamp"])
        assert entered >= floor, (
            f"{r['ticker']} entered {entered} — before cohort start {floor}. "
            "The live cohort is leaking a disowned era."
        )


def test_all_eras_is_a_superset_and_is_not_cohort_floored():
    """The escape hatch must still reach history, and must say it is unfloored."""
    live = get_position_history(days=LOOKBACK)
    every = get_position_history(days=LOOKBACK, policy_version="all")
    assert "error" not in every, every
    assert every.get("cohort_start") is None
    assert every["row_count"] >= live["row_count"]


def test_empty_live_cohort_declares_itself():
    """A zero here must not read as 'no track record'. If the cohort is empty,
    the response has to say WHY, where the wrong conclusion gets drawn."""
    out = get_historical_performance(lookback_days=LOOKBACK)
    assert "error" not in out, out
    assert out.get("cohort_start") == LIVE_COHORT_START_DATE
    if out["total_trades"] == 0:
        blob = f"{out.get('period', '')} {out.get('note') or ''}".lower()
        assert LIVE_COHORT_START_DATE in blob
        assert "cohort" in blob
        assert "not missing data" in blob or "not that there is no track" in blob


def test_no_fabricated_stats_when_rows_exist_but_returns_are_all_null():
    """The sneaky path: `rows` is non-empty so the self-describing empty branch
    is skipped, but every realized_return_pct is NULL, so there is still nothing
    to average. A 0.0 here would be an UNDISCLOSED fabrication. Not reachable
    from today's BigQuery data, so it is stubbed at the client boundary."""
    import tools.historical as H

    class _Row:
        realized_return_pct = None

    class _Job:
        def result(self):
            return [_Row(), _Row()]

    class _Client:
        def query(self, *a, **k):
            return _Job()

    real = H.client
    H.client = _Client()
    try:
        out = H.get_historical_performance(lookback_days=30)
    finally:
        H.client = real

    assert out["total_trades"] == 0
    for k in _STAT_KEYS:
        assert out[k] is None, f"{k} is {out[k]!r} with rows present but no returns"
    assert "Not investment advice" in (out.get("note") or "")


def test_no_fabricated_stats_at_zero_n():
    """A consumer extracts KEYS, not prose. `win_rate: 0.0` on an empty cohort
    reads as "0% win rate" and `best: 0.0` as "best trade was breakeven" — both
    invented. At N=0 every aggregate must be null."""
    out = get_historical_performance(lookback_days=LOOKBACK)
    if out["total_trades"] == 0:
        for k in _STAT_KEYS:
            assert out[k] is None, f"{k} is {out[k]!r} at N=0 — fabricated statistic"


def test_every_performance_response_carries_the_compliance_tail():
    """An empty result is still a performance claim about a paid product. The
    disclaimer must not be conditional on there being rows."""
    for kwargs in ({}, {"policy_version": "all"}):
        out = get_historical_performance(lookback_days=LOOKBACK, **kwargs)
        note = out.get("note") or ""
        assert "Not investment advice" in note, f"missing disclaimer for {kwargs}"


def test_all_eras_warns_that_it_includes_disowned_cohorts():
    """The docstrings advertise policy_version="all" as the way to see more, so
    an agent that gets 0 will reach for it. It must not hand back repudiated
    rows as though they were a track record."""
    for out in (
        get_historical_performance(lookback_days=LOOKBACK, policy_version="all"),
        get_position_history(days=LOOKBACK, policy_version="all"),
    ):
        note = out.get("note") or ""
        assert DISOWNED_COHORT_NOTE in note
        assert "DISOWNED" in note
        assert "2026-07-29" in note, "the disowned reset dates must be named"


def test_historical_live_cohort_never_counts_pre_cohort_trades():
    """Aggregate arm of the same guard: the live aggregate must never exceed
    what the date-floored cohort can contain."""
    live = get_historical_performance(lookback_days=LOOKBACK)
    every = get_historical_performance(lookback_days=LOOKBACK, policy_version="all")
    assert live["total_trades"] <= every["total_trades"]
    # The disowned 2026-07-29 cohort is inside `all` but must be outside `live`.
    if every["total_trades"] > 0 and live["total_trades"] == every["total_trades"]:
        pytest.fail(
            "live cohort aggregate equals the all-eras aggregate — the date "
            "floor is not being applied (this is exactly the 2026-08-07 bug)."
        )
