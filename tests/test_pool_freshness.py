"""
get_market_calendar_status(view="freshness") — pool-freshness/1 (2026-09-29).

The VM trader stands the day down unless this view says the pool is fresh, so
these tests pin the contract it parses: each stage's rule, the fail-closed
unknowns, the NYSE expected_scan_date (never calendar subtraction), and that
pool_scan_date is the date get_pool(view="enriched") really serves. A fake
BigQuery client stands in for the network; the NYSE calendar is the real one.

    PYTHONPATH=src .venv/bin/python -m pytest tests/test_pool_freshness.py -q
"""

from __future__ import annotations

import sys
import time
from datetime import datetime

import pytest

sys.path.insert(0, "src")

from tools import (  # noqa: E402
    freshness,
    metadata,
    overnight_signals,
    v4,  # noqa: E402
)
from utils import data  # noqa: E402

ET = freshness.ET


class Row(dict):
    """A BigQuery Row stand-in: attribute access AND dict(row)."""

    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError as e:
            raise AttributeError(k) from e


class FakeBQ:
    """Answers the freshness stage queries and get_pool's enriched path.

    counts[stage][date] = rows for that date; the stage's latest_date is the
    max date with rows. pool_max is what MAX(scan_date) on the safe view
    returns; pool_rows[date] is how many rows the enriched pool query returns.
    """

    def __init__(self, counts, pool_max, pool_rows, fail=(), sleep=None, expected=None):
        self.counts = counts
        # expected[date] = enrichment's expected_rows; default from the scan.
        self.expected = expected or {}
        self.pool_max = pool_max
        self.pool_rows = pool_rows
        self.fail = set(fail)
        self.sleep = sleep or {}
        self.calls = []

    def _stage(self, sql):
        for tag in ("scan", "enrichment", "liquidity"):
            if f"-- freshness:{tag}" in sql:
                return tag
        if "MAX(scan_date) as max_date" in sql:
            return "pool_max"
        if "WHERE scan_date = @scan_date" in sql:
            return "pool_rows"
        raise AssertionError(f"unexpected query: {sql[:120]}")

    def query(self, sql, job_config=None):
        stage = self._stage(sql)
        self.calls.append(stage)
        # QueryJobConfig round-trips a DATE parameter to datetime.date.
        params = {
            p.name: p.value.isoformat() if hasattr(p.value, "isoformat") else p.value
            for p in (job_config.query_parameters if job_config else [])
        }
        return _Job(self, stage, params)


class _Job:
    def __init__(self, bq, stage, params):
        self.bq, self.stage, self.params = bq, stage, params

    def result(self, timeout=None):
        bq, stage = self.bq, self.stage
        if stage in bq.sleep:
            time.sleep(bq.sleep[stage])
        pool_stage = "pool" if stage.startswith("pool") else stage
        if pool_stage in bq.fail:
            raise RuntimeError(f"boom on {pool_stage} profitscout-fida8.profit_scout.x")
        if stage == "pool_max":
            return [Row(max_date=bq.pool_max)]
        if stage == "pool_rows":
            n = bq.pool_rows.get(self.params["scan_date"], 0)
            return [Row(scan_date=self.params["scan_date"], ticker=f"T{i}") for i in range(n)][
                : self.params["limit"]
            ]
        by_date = bq.counts.get(stage, {})
        latest = max((d for d, n in by_date.items() if n > 0), default=None)
        d = self.params["d"]
        row = Row(latest_date=latest, n=by_date.get(d, 0))
        if stage == "enrichment":
            # Default: every scanned name qualifies, capped at 50, as on a
            # normal day. A missing scan gives 0.
            row["expected_n"] = bq.expected.get(d, min(50, bq.counts.get("scan", {}).get(d, 0)))
        return [row]


@pytest.fixture
def install(monkeypatch):
    def _install(bq):
        monkeypatch.setattr(freshness, "client", bq)
        monkeypatch.setattr(overnight_signals, "client", bq)
        return bq

    return _install


def at(y, m, d, hh=9, mm=45):
    return datetime(y, m, d, hh, mm, tzinfo=ET)


# Tue 2026-09-29 09:45 ET: the trader's preflight. Expected scan = Mon 09-28.
TUE = at(2026, 9, 29)


def healthy(expected="2026-09-28", prior="2026-09-25"):
    return FakeBQ(
        counts={
            "scan": {prior: 100, expected: 100},
            "enrichment": {prior: 50, expected: 50},
            "liquidity": {prior: 50, expected: 50},
        },
        pool_max=expected,
        pool_rows={prior: 50, expected: 50},
    )


# ---------------------------------------------------------------- contract --
def test_all_stages_current_is_fresh(install):
    install(healthy())
    r = freshness.get_pool_freshness(now_et=TUE)
    assert r["schema"] == "pool-freshness/1"
    assert r["today"] == "2026-09-29"
    assert r["is_session_today"] is True
    assert r["expected_scan_date"] == "2026-09-28"
    assert r["as_of_et"] == "2026-09-29T09:45:00-04:00"
    for name, table in (
        ("scan", "overnight_signals"),
        ("enrichment", "overnight_signals_enriched_safe"),
        ("liquidity", "pool_liquidity_snapshot"),
    ):
        s = r["stages"][name]
        assert s["table"] == table
        assert s["latest_date"] == "2026-09-28"
        assert s["ok"] is True and s["due"] is True
    assert r["stages"]["scan"]["rows"] == 100
    assert r["stages"]["enrichment"]["expected_rows"] == 50
    assert r["pool_scan_date"] == "2026-09-28"
    assert r["pool_rows"] == 50
    assert r["fresh"] is True
    assert r["reasons"] == []


def test_scanner_ran_enrichment_did_not(install):
    # The liquidity writer keys on the expected pool and skips when there is
    # none, so a missed enrichment also leaves no liquidity rows. get_pool
    # still serves the prior pool.
    bq = healthy()
    bq.counts["enrichment"].pop("2026-09-28")
    bq.counts["liquidity"].pop("2026-09-28")
    bq.pool_max = "2026-09-25"
    install(bq)
    r = freshness.get_pool_freshness(now_et=TUE)
    assert r["reasons"] == ["enrichment-stale", "liquidity-stale", "pool-stale"]
    assert r["stages"]["scan"]["ok"] is True
    assert r["stages"]["enrichment"]["ok"] is False
    assert r["stages"]["enrichment"]["latest_date"] == "2026-09-25"
    assert r["pool_scan_date"] == "2026-09-25"
    assert r["fresh"] is False


def test_scanner_did_not_run(install):
    bq = healthy()
    for stage in ("scan", "enrichment", "liquidity"):
        bq.counts[stage].pop("2026-09-28")
    bq.pool_max = "2026-09-25"
    install(bq)
    r = freshness.get_pool_freshness(now_et=TUE)
    assert r["reasons"][0] == "scan-stale"
    assert r["stages"]["scan"] == {
        "table": "overnight_signals",
        "latest_date": "2026-09-25",
        "rows": 0,
        "ok": False,
        "due": True,
    }
    assert r["fresh"] is False


def test_pool_serves_zero_rows(install):
    bq = healthy()
    bq.pool_rows["2026-09-28"] = 0
    install(bq)
    r = freshness.get_pool_freshness(now_et=TUE)
    assert r["pool_scan_date"] == "2026-09-28"
    assert r["pool_rows"] == 0
    assert r["reasons"] == ["pool-empty"]
    assert r["fresh"] is False


def test_empty_enriched_view(install):
    bq = healthy()
    bq.pool_max = None
    install(bq)
    r = freshness.get_pool_freshness(now_et=TUE)
    assert r["pool_scan_date"] is None and r["pool_rows"] == 0
    assert r["reasons"] == ["pool-stale", "pool-empty"]


@pytest.mark.parametrize("stage", ["scan", "enrichment", "liquidity"])
def test_bigquery_error_on_one_stage_fails_closed(install, stage):
    bq = healthy()
    bq.fail = {stage}
    install(bq)
    r = freshness.get_pool_freshness(now_et=TUE)
    s = r["stages"][stage]
    assert s["ok"] is None and s["rows"] is None and s["latest_date"] is None
    assert "profitscout" not in s["error"]  # redacted by safe_error
    assert r["reasons"] == [f"unknown-{stage}"]
    assert r["fresh"] is False
    for other in {"scan", "enrichment", "liquidity"} - {stage}:
        assert r["stages"][other]["ok"] is True


def test_bigquery_error_on_pool_fails_closed(install):
    bq = healthy()
    bq.fail = {"pool"}
    install(bq)
    r = freshness.get_pool_freshness(now_et=TUE)
    assert r["pool_scan_date"] is None and r["pool_rows"] is None
    assert r["reasons"] == ["unknown-pool"]
    assert r["fresh"] is False


def test_no_bigquery_client_is_all_unknown(install):
    install(None)
    r = freshness.get_pool_freshness(now_et=TUE)
    assert r["reasons"] == [
        "unknown-scan",
        "unknown-enrichment",
        "unknown-liquidity",
        "unknown-pool",
    ]
    assert r["fresh"] is False


def test_stage_past_deadline_is_unknown(install, monkeypatch):
    monkeypatch.setattr(freshness, "DEADLINE_S", 0.3)
    bq = healthy()
    bq.sleep = {"liquidity": 1.0}
    install(bq)
    t0 = time.monotonic()
    r = freshness.get_pool_freshness(now_et=TUE)
    assert time.monotonic() - t0 < 0.9
    assert r["stages"]["liquidity"]["ok"] is None
    assert r["reasons"] == ["unknown-liquidity"]
    assert r["fresh"] is False


# ---------------------------------------------------------------- calendar --
def test_monday_expects_friday(install):
    install(healthy(expected="2026-09-25", prior="2026-09-24"))
    r = freshness.get_pool_freshness(now_et=at(2026, 9, 28))
    assert r["expected_scan_date"] == "2026-09-25"
    assert r["fresh"] is True


def test_day_after_holiday_expects_last_session(install):
    # Mon 2026-09-07 is Labor Day. Tue 09-08 trades the Fri 09-04 scan, which
    # the weekday enrichment cron enriched on the holiday morning.
    install(healthy(expected="2026-09-04", prior="2026-09-03"))
    r = freshness.get_pool_freshness(now_et=at(2026, 9, 8))
    assert r["expected_scan_date"] == "2026-09-04"
    assert r["is_session_today"] is True
    assert r["fresh"] is True


def test_holiday_itself_is_not_a_session(install):
    install(healthy(expected="2026-09-04", prior="2026-09-03"))
    r = freshness.get_pool_freshness(now_et=at(2026, 9, 7, 10, 0))
    assert r["is_session_today"] is False
    assert r["expected_scan_date"] == "2026-09-04"
    # No session today, so no liquidity snapshot is due.
    assert r["stages"]["liquidity"]["due"] is False


# ------------------------------------------------------------- due windows --
def test_before_liquidity_window_is_not_a_failure(install):
    bq = healthy()
    bq.counts["liquidity"].pop("2026-09-28")
    install(bq)
    r = freshness.get_pool_freshness(now_et=at(2026, 9, 29, 8, 0))
    liq = r["stages"]["liquidity"]
    assert liq["due"] is False and liq["ok"] is True and liq["rows"] == 0
    assert r["fresh"] is True


def test_liquidity_overdue_after_window(install):
    bq = healthy()
    bq.counts["liquidity"].pop("2026-09-28")
    install(bq)
    r = freshness.get_pool_freshness(now_et=at(2026, 9, 29, 9, 40))
    assert r["stages"]["liquidity"]["due"] is True
    assert r["reasons"] == ["liquidity-stale"]


def test_before_enrichment_cron_pool_not_ready(install):
    # 04:00 ET: the 05:30 enrichment has not run. Nothing is overdue, but the
    # pool for today does not exist yet, so the pool is not fresh.
    bq = healthy()
    bq.counts["enrichment"].pop("2026-09-28")
    bq.counts["liquidity"].pop("2026-09-28")
    bq.pool_max = "2026-09-25"
    install(bq)
    r = freshness.get_pool_freshness(now_et=at(2026, 9, 29, 4, 0))
    assert r["stages"]["enrichment"]["due"] is False
    assert r["stages"]["enrichment"]["ok"] is True
    assert r["reasons"] == ["pool-stale"]
    assert r["fresh"] is False


# ------------------------------------------------------------ pool parity --
@pytest.mark.parametrize("served", ["2026-09-28", "2026-09-25"])
def test_pool_scan_date_is_what_get_pool_serves(install, served):
    bq = healthy()
    bq.pool_max = served
    install(bq)
    r = freshness.get_pool_freshness(now_et=TUE)
    rows = v4.get_pool(view="enriched", limit=60)
    assert rows and all(row["scan_date"] == served for row in rows)
    assert r["pool_scan_date"] == served
    assert r["pool_rows"] == len(rows)


def test_pool_uses_the_shared_helper(install, monkeypatch):
    install(healthy())
    seen = []
    real = overnight_signals.latest_enriched_scan_date

    def spy():
        seen.append(1)
        return real()

    monkeypatch.setattr(overnight_signals, "latest_enriched_scan_date", spy)
    freshness.get_pool_freshness(now_et=TUE)
    assert seen, "pool_scan_date must come from get_pool's own helper"


def test_pool_rows_respects_get_pool_clamp(install):
    bq = healthy()
    bq.pool_rows["2026-09-28"] = 75
    install(bq)
    r = freshness.get_pool_freshness(now_et=TUE)
    assert r["pool_rows"] == 50  # get_enriched_signals clamps limit to 50


# ------------------------------------------------------------------- cache --
def test_success_is_cached_failure_is_not(install, monkeypatch):
    monkeypatch.setattr(freshness, "_cache", None)
    bq = install(healthy())
    bq.fail = {"scan"}
    freshness.get_pool_freshness()
    freshness.get_pool_freshness()
    assert bq.calls.count("scan") == 2  # the unknown result was not cached
    bq.fail = set()
    first = freshness.get_pool_freshness()
    first["fresh"] = "mutated by caller"
    second = freshness.get_pool_freshness()
    assert bq.calls.count("scan") == 3  # served from cache
    assert second["fresh"] != "mutated by caller"
    monkeypatch.setattr(freshness, "_cache", None)


# --------------------------------------------------- other views untouched --
class _NoBQ:
    def __getattr__(self, name):
        raise AssertionError(f"view='status' touched BigQuery ({name})")


def test_status_view_unchanged_and_makes_no_bigquery_call(monkeypatch):
    for mod in (data, freshness, overnight_signals, metadata):
        attr = "BQ" if mod is data else "client"
        monkeypatch.setattr(mod, attr, _NoBQ())
    r = v4.get_market_calendar_status(view="status")
    assert set(r) == {
        "is_open_today",
        "current_date",
        "current_time_et",
        "next_open",
        "next_close",
        "is_holiday",
        "holiday_name",
        "is_early_close",
    }
    assert set(v4.get_market_calendar_status()) == set(r)  # still the default view


def test_unknown_view_lists_freshness():
    r = v4.get_market_calendar_status(view="nope")
    assert r["allowed"] == ["status", "scan_dates", "freshness"]


def test_freshness_view_dispatches(install, monkeypatch):
    monkeypatch.setattr(freshness, "_cache", None)
    install(healthy())
    r = v4.get_market_calendar_status(view="freshness")
    assert r["schema"] == "pool-freshness/1"
    monkeypatch.setattr(freshness, "_cache", None)


# ---------------------------------------------------------- expected_rows --
def test_partial_enrichment_is_reported_not_judged(install):
    # 40 of 50 expected rows landed. The view reports both numbers; the
    # completeness test belongs to the consumer.
    bq = healthy()
    bq.counts["enrichment"]["2026-09-28"] = 40
    bq.expected = {"2026-09-28": 50}
    install(bq)
    r = freshness.get_pool_freshness(now_et=TUE)
    enr = r["stages"]["enrichment"]
    assert enr["rows"] == 40 and enr["expected_rows"] == 50
    assert enr["ok"] is True


def test_nothing_to_enrich_is_not_enrichment_stale(install):
    # The scan ran but no name qualified (no BULLISH name on a hard selloff).
    # Enrichment had nothing to write, so it is not overdue. get_pool still
    # serves the prior pool, so the day is not fresh.
    bq = healthy()
    bq.counts["enrichment"].pop("2026-09-28")
    bq.counts["liquidity"].pop("2026-09-28")
    bq.expected = {"2026-09-28": 0}
    bq.pool_max = "2026-09-25"
    install(bq)
    r = freshness.get_pool_freshness(now_et=TUE)
    enr = r["stages"]["enrichment"]
    assert enr["rows"] == 0 and enr["expected_rows"] == 0 and enr["ok"] is True
    assert "enrichment-stale" not in r["reasons"]
    assert "pool-stale" in r["reasons"]
    assert r["fresh"] is False


def test_enrichment_error_nulls_expected_rows(install):
    bq = healthy()
    bq.fail = {"enrichment"}
    install(bq)
    enr = freshness.get_pool_freshness(now_et=TUE)["stages"]["enrichment"]
    assert enr["expected_rows"] is None and enr["ok"] is None


def test_expected_rows_sql_mirrors_the_enrichment_filter():
    # The live query is BigQuery; pin the filter text so a drift is a diff.
    captured = {}

    class _Capture:
        def query(self, sql, job_config=None):
            captured["sql"] = sql
            return _Job(healthy(), "enrichment", {"d": "2026-09-28"})

    orig = freshness.client
    freshness.client = _Capture()
    try:
        freshness._enrichment_stage(datetime(2026, 9, 28).date())
    finally:
        freshness.client = orig
    sql = " ".join(captured["sql"].split())
    for part in (
        "LEAST(COUNT(*), 50)",
        "direction = 'BULLISH'",
        "overnight_score >= 1",
        "recommended_spread_pct <= 0.3",
        "liquidity_rank <= 100",
    ):
        assert part in sql, part
