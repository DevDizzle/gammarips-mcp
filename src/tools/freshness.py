"""
Pool freshness for GammaRips MCP (2026-09-29).

`get_market_calendar_status(view="freshness")` tells an agent whether the pool
it is about to trade is the right pool. It returns the pipeline facts an agent
cannot see from the pool rows: did the 23:00 ET scanner run, did the 05:30 ET
enrichment run, is the liquidity writer re-reading the pool. The VM trader
(gammarips-trader guard.py) reads this object at 09:45 ET and again before
each entry, and stands the day down unless it is fresh.

Contract `pool-freshness/1` (the trader parses these field names; change the
schema string if a field changes):

    schema, as_of_et, today, is_session_today, expected_scan_date,
    stages{scan|enrichment|liquidity: {table, latest_date, rows, ok, due}},
    pool_scan_date, pool_rows, fresh, reasons[]

expected_scan_date = the last NYSE session before today (the same
pandas_market_calendars XNYS calendar as view="status"). Never calendar
subtraction: that is wrong on every Monday and after every holiday.

Per-stage rules. `rows` counts expected_scan_date. `ok` is True when the stage
has produced everything it is DUE to have produced by now, False when it is
overdue, and None when the check could not run. A stage that is not yet due
reports ok=True with due=False: a job that has not run yet is not a failure
(the digest's own rule, dbt-runner/digest.py coverage_section: "trailing zeros
are simply hasn't-run-yet", and the 2026-09-01 open_past_due fix in this repo).

  * scan — `overnight_signals`. latest_date = MAX(scan_date). rows =
    COUNT(*) WHERE scan_date = expected (the digest's COUNT(*), re-scan
    duplicates included). Due from 23:30 ET on expected_scan_date (the
    scanner fires 23:00 ET), so it is always due once that day is over.
    ok = rows > 0.
  * enrichment — `overnight_signals_enriched_safe`, the leakage-safe view that
    get_pool serves (row counts equal the raw table the digest reads; this
    server never reads the raw table). latest_date = MAX(scan_date). rows =
    COUNT(*) WHERE scan_date = expected. Due from 06:00 ET on the first
    weekday after expected_scan_date (the enrichment cron is 05:30 ET Mon-Fri
    and finishes by ~05:33; it runs on NYSE holidays too). ok = rows > 0.
  * liquidity — `pool_liquidity_snapshot`. The digest dates this table by
    DATE(as_of), the session morning, not the scan date. The writer ALSO
    stamps every row with the scan_date of the pool it re-read, and that is
    the column used here, so all three latest_date values share one axis.
    latest_date = MAX(scan_date). rows = contracts in the newest snapshot of
    the expected pool. Due from 09:40 ET on a session day (the writer's
    first pass lands ~09:22 ET, then every 10 min; 09:40 allows one retry).
    On a non-session day the next snapshot is not due. ok = rows > 0.

Pool: pool_scan_date is the scan_date get_pool(view="enriched") serves when
the caller passes none. It comes from `latest_enriched_scan_date()`, the ONE
helper get_enriched_signals itself calls, so the two cannot differ. pool_rows
is the length of the list get_enriched_signals(scan_date=pool_scan_date,
limit=60) returns (that path clamps limit to 50).

fresh = every stage ok is True AND pool_scan_date == expected_scan_date AND
pool_rows > 0. Consequence, by design: before 06:00 ET on a session day, and
on a weekend or holiday before the next enrichment, fresh is False with every
stage ok and reason "pool-stale". That is literal: the pool for the next trade
does not exist yet.

Fail closed: a stage whose query errors or misses the deadline gets ok=None,
an `unknown-<stage>` reason, and fresh=False. A check that could not run is
never fresh. No row floor is applied here; the trader applies its own. The
result is cached for at most 60 s, and a result with any unknown is never
cached. Deterministic: BigQuery + the NYSE calendar, no LLM.
"""

from __future__ import annotations

import copy
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import date, datetime, timedelta
from datetime import time as dtime
from typing import Any
from zoneinfo import ZoneInfo

from google.cloud import bigquery

from tools import overnight_signals
from utils.data import BQ as client
from utils.data import POOL_LIQUIDITY_TABLE as _POOL_LIQ
from utils.data import RAW_SCAN_TABLE as _RAW_SCAN
from utils.data import SAFE_ENRICHED_TABLE as _SAFE_ENRICHED
from utils.safety import safe_error

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
SCHEMA = "pool-freshness/1"

# When each stage's output for expected_scan_date is due (ET). Tied to the
# engine's Cloud Scheduler crons: overnight-scanner-trigger 0 23 * * 1-5,
# enrichment-trigger-daily 30 5 * * 1-5, pool-liquidity-refresh 2-52/10 9-16
# (self-gated to 09:15-16:05, first pass ~09:22). Move these if a cron moves.
SCAN_DUE_ET = dtime(23, 30)
ENRICHMENT_DUE_ET = dtime(6, 0)
LIQUIDITY_DUE_ET = dtime(9, 40)

# get_pool(view="enriched", limit=60): the limit the trader passes.
POOL_LIMIT = 60

# Whole-check hard deadline. A stage still running at the deadline is unknown,
# and an unknown stands the trader down for the day, so this is set well above
# the typical latency rather than at the 3 s target: a slow BigQuery answer
# must not cost a trading day. The stages run in parallel; the pool stage is
# two sequential jobs (it reuses get_pool's own path) and is the long pole.
DEADLINE_S = 8.0
_QUERY_TIMEOUT_S = 7.5
CACHE_TTL_S = 60.0

_STAGE_ORDER = ("scan", "enrichment", "liquidity")

_cache_lock = threading.Lock()
_cache: tuple[float, dict[str, Any]] | None = None


def _bare(table: str) -> str:
    """`proj.dataset.name` -> name, for the response's `table` field."""
    return table.strip("`").rsplit(".", 1)[-1]


# --------------------------------------------------------------------------
# calendar
# --------------------------------------------------------------------------
def _sessions(today: date) -> list[date]:
    """NYSE sessions from 21 days before `today` through `today` inclusive.
    21 days covers every multi-day NYSE closure on record."""
    import pandas_market_calendars as mcal

    nyse = mcal.get_calendar("XNYS")
    sched = nyse.schedule(
        start_date=(today - timedelta(days=21)).isoformat(),
        end_date=today.isoformat(),
    )
    return [ts.date() for ts in sched.index]


def _first_weekday_after(d: date) -> date:
    n = d + timedelta(days=1)
    while n.weekday() >= 5:
        n += timedelta(days=1)
    return n


def _at(d: date, t: dtime) -> datetime:
    return datetime.combine(d, t, tzinfo=ET)


# --------------------------------------------------------------------------
# stage queries (each one query, so one failure marks one stage unknown)
# --------------------------------------------------------------------------
def _run(sql: str, expected: date) -> tuple[str | None, int]:
    if client is None:
        raise RuntimeError("BigQuery client not initialized")
    cfg = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("d", "DATE", expected.isoformat())]
    )
    for row in client.query(sql, job_config=cfg).result(timeout=_QUERY_TIMEOUT_S):
        latest = row.latest_date
        return (str(latest) if latest else None), int(row.n or 0)
    return None, 0


def _scan_stage(expected: date) -> tuple[str | None, int]:
    return _run(
        f"""-- freshness:scan
        SELECT
          (SELECT MAX(scan_date) FROM {_RAW_SCAN}) AS latest_date,
          (SELECT COUNT(*) FROM {_RAW_SCAN} WHERE scan_date = @d) AS n""",
        expected,
    )


def _enrichment_stage(expected: date) -> tuple[str | None, int]:
    return _run(
        f"""-- freshness:enrichment
        SELECT
          (SELECT MAX(scan_date) FROM {_SAFE_ENRICHED}) AS latest_date,
          (SELECT COUNT(*) FROM {_SAFE_ENRICHED} WHERE scan_date = @d) AS n""",
        expected,
    )


def _liquidity_stage(expected: date) -> tuple[str | None, int]:
    return _run(
        f"""-- freshness:liquidity
        SELECT
          (SELECT MAX(scan_date) FROM {_POOL_LIQ}) AS latest_date,
          (SELECT COUNT(DISTINCT contract) FROM {_POOL_LIQ}
            WHERE scan_date = @d
              AND as_of = (SELECT MAX(as_of) FROM {_POOL_LIQ} WHERE scan_date = @d)
          ) AS n""",
        expected,
    )


def _pool() -> tuple[str | None, int]:
    """(pool_scan_date, pool_rows) through get_pool's own code path."""
    if client is None:
        raise RuntimeError("BigQuery client not initialized")
    scan_date = overnight_signals.latest_enriched_scan_date()
    if not scan_date:
        return None, 0
    rows = overnight_signals.get_enriched_signals(scan_date=scan_date, limit=POOL_LIMIT)
    if rows and isinstance(rows[0], dict) and "error" in rows[0]:
        raise RuntimeError(rows[0]["error"])
    return scan_date, len(rows)


_STAGES = {
    "scan": (_RAW_SCAN, _scan_stage),
    "enrichment": (_SAFE_ENRICHED, _enrichment_stage),
    "liquidity": (_POOL_LIQ, _liquidity_stage),
}


# --------------------------------------------------------------------------
# the view
# --------------------------------------------------------------------------
def _check(now_et: datetime) -> dict[str, Any]:
    today = now_et.date()
    try:
        sessions = _sessions(today)
        is_session_today = today in sessions
        expected = max(d for d in sessions if d < today)
    except Exception as e:  # noqa: BLE001
        # No calendar, no expected date, no check. Fail closed.
        return {
            "schema": SCHEMA,
            "as_of_et": now_et.isoformat(timespec="seconds"),
            "today": today.isoformat(),
            "fresh": False,
            "reasons": ["unknown-calendar"],
            "error": safe_error(e, "pool_freshness (calendar)"),
        }

    due_at = {
        "scan": _at(expected, SCAN_DUE_ET),
        "enrichment": _at(_first_weekday_after(expected), ENRICHMENT_DUE_ET),
        # The first session after `expected` is today when today is a session.
        # Otherwise it is in the future and the next snapshot is not due.
        "liquidity": _at(today, LIQUIDITY_DUE_ET) if is_session_today else None,
    }

    pool_ex = ThreadPoolExecutor(max_workers=4, thread_name_prefix="freshness")
    try:
        futures = {name: pool_ex.submit(fn, expected) for name, (_, fn) in _STAGES.items()}
        futures["pool"] = pool_ex.submit(_pool)
        wait(list(futures.values()), timeout=DEADLINE_S)
    finally:
        # Do not block the response on a straggler; its result is discarded.
        pool_ex.shutdown(wait=False, cancel_futures=True)

    def _outcome(name: str) -> tuple[Any, str | None]:
        fut = futures[name]
        if not fut.done():
            logger.warning("pool_freshness: %s missed the %.1fs deadline", name, DEADLINE_S)
            return None, f"{name} check exceeded the {DEADLINE_S}s deadline"
        try:
            return fut.result(), None
        except Exception as e:  # noqa: BLE001
            return None, safe_error(e, f"pool_freshness ({name})")

    stages: dict[str, dict[str, Any]] = {}
    reasons: list[str] = []
    for name in _STAGE_ORDER:
        table, _ = _STAGES[name]
        due = due_at[name] is not None and now_et >= due_at[name]
        result, err = _outcome(name)
        if err is not None:
            stages[name] = {
                "table": _bare(table),
                "latest_date": None,
                "rows": None,
                "ok": None,
                "due": due,
                "error": err,
            }
            reasons.append(f"unknown-{name}")
            continue
        latest, n = result
        ok = n > 0 if due else True
        stages[name] = {
            "table": _bare(table),
            "latest_date": latest,
            "rows": n,
            "ok": ok,
            "due": due,
        }
        if not ok:
            reasons.append(f"{name}-stale")

    pool_result, pool_err = _outcome("pool")
    if pool_err is not None:
        pool_scan_date, pool_rows = None, None
        reasons.append("unknown-pool")
    else:
        pool_scan_date, pool_rows = pool_result
        if pool_scan_date != expected.isoformat():
            reasons.append("pool-stale")
        if pool_rows == 0:
            reasons.append("pool-empty")

    out: dict[str, Any] = {
        "schema": SCHEMA,
        "as_of_et": now_et.isoformat(timespec="seconds"),
        "today": today.isoformat(),
        "is_session_today": is_session_today,
        "expected_scan_date": expected.isoformat(),
        "stages": stages,
        "pool_scan_date": pool_scan_date,
        "pool_rows": pool_rows,
        "fresh": not reasons,
        "reasons": reasons,
    }
    if pool_err is not None:
        out["pool_error"] = pool_err
    return out


def _cacheable(result: dict[str, Any]) -> bool:
    return not any(r.startswith("unknown-") for r in result.get("reasons", []))


def get_pool_freshness(now_et: datetime | None = None) -> dict[str, Any]:
    """Is today's pool the right pool, and did every stage that feeds it run?
    See the module docstring for the contract and the per-stage rules.
    `now_et` is for tests; a supplied value bypasses the cache."""
    global _cache
    if now_et is not None:
        return _check(now_et)
    mono = time.monotonic()
    with _cache_lock:
        if _cache is not None and mono - _cache[0] < CACHE_TTL_S:
            return copy.deepcopy(_cache[1])
    result = _check(datetime.now(ET))
    if _cacheable(result):
        with _cache_lock:
            _cache = (mono, copy.deepcopy(result))
    return result
