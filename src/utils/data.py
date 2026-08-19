"""
Shared data layer for the GammaRips MCP server (V4).

One BigQuery client, one Firestore client, and every fully-qualified
table / view / collection identifier in a single place. Individual tool
modules import the clients + constants from here instead of each
constructing their own client with a hardcoded project id (the V3 state:
five modules built their own BQ client and `_MINUTE_PATHS_TABLE` was
defined twice — in substrate.py and contract_history.py).

Clients are module-level singletons, guarded: a missing / failed client
degrades to None (every tool already guards `if not client:`), it never
crashes the server. Project id comes from GCP_PROJECT_ID (defaulting to the
production project) so a non-prod deploy points itself.

NOTE: `utils.auth` keeps its OWN lazy Firestore client for the api-key
lookup path — that is auth plumbing (verified working) and is deliberately
left untouched. `FS` here is the DATA-read Firestore client (daily reports).
"""

from __future__ import annotations

import logging
import os

from google.cloud import bigquery, firestore

logger = logging.getLogger(__name__)

PROJECT_ID = os.getenv("GCP_PROJECT_ID", "profitscout-fida8")
DATASET = "profit_scout"
# Unquoted dataset FQN — for building INFORMATION_SCHEMA references and any
# place a table name is compared as a string literal (see metadata.py).
DATASET_FQN = f"{PROJECT_ID}.{DATASET}"


def _t(name: str) -> str:
    """Backtick-quoted, fully-qualified table/view identifier for SQL."""
    return f"`{DATASET_FQN}.{name}`"


# --- BigQuery tables / views ------------------------------------------------
SAFE_ENRICHED_TABLE = _t("overnight_signals_enriched_safe")
RAW_SCAN_TABLE = _t("overnight_signals")
FEATURES_VIEW = _t("enriched_features_v1")
OUTCOMES_TABLE = _t("enriched_option_outcomes")
MINUTE_PATHS_TABLE = _t("option_minute_paths")
POOL_LIQUIDITY_TABLE = _t("pool_liquidity_snapshot")
FORWARD_PAPER_LEDGER = _t("forward_paper_ledger")
SIGNAL_PERFORMANCE_TABLE = _t("signal_performance")

# --- live paper cohort ------------------------------------------------------
# THE cohort definition, in one place. It is a (policy label, start date) PAIR;
# the label alone is NOT sufficient. `forward_paper_ledger` is no longer
# truncated at every cutover — since 2026-07-28 cohort resets are DATE-FILTER
# resets, so rows from disowned cohorts remain in the table carrying the same
# `policy_version`. Filtering on the label alone silently serves them.
#
# Mirrors `signal-notifier/main.py::LIVE_COHORT_START_DATE` in ../gammarips-engine.
# When the engine resets its cohort this MUST move with it — these two
# constants drifting apart IS the 2026-08-07 defect: this repo said
# "since 2026-06-26" through two resets, so the MCP served the disowned
# 2026-07-29 cohort as live receipts (including two picks the engine had
# established were selected on a phantom liquidity count).
#
# Cohort history: 2026-06-26 (live-OI floor) -> 2026-07-29 (tournament
# liquidity upgrade) -> 2026-08-10 (stale-day-bar fix; the 07-29 cohort's
# primary print floor never actually fired) -> 2026-08-13 (fail-soft restore
# can never become the pick; 2 of the 08-10 cohort's 3 entries were restores
# the new code cannot select). See the engine's
# docs/DECISIONS/2026-08-07-stale-day-bar-early-volume.md and
# docs/DECISIONS/2026-08-12-failsoft-restore-never-picks.md.
# NOTE on the predicate, not just the constant: the engine's own cohort_stats
# query (`signal-notifier/main.py`) writes `DATE(entry_timestamp) >= ...` with
# NO timezone argument, i.e. UTC-dated; this repo dates in ET. The two agree in
# practice only because V7.1 entries land 10:00-15:45 ET (14:00-19:45 UTC), so
# the UTC and ET calendar dates are always equal. An entry stamped >= 20:00 ET
# would break that equivalence. ET is the more correct of the two — do not
# "fix" it toward the engine's UTC form.
LIVE_POLICY_VERSION = "V7_1_TILTED_GIGO"
LIVE_COHORT_START_DATE = "2026-08-13"

# Compliance tail. MUST ride every response that carries performance numbers,
# including the EMPTY ones — an empty cohort response is still a performance
# claim about a paid product.
_PAPER_DISCLAIMER = "Paper-traded. Not investment advice."

LIVE_COHORT_NOTE = (
    "Live cohort = policy_version='V7_1_TILTED_GIGO' AND entry on/after "
    "2026-08-13. The ledger retains earlier cohorts under the SAME policy "
    "label (resets are date-filter only, not truncations), so the label alone "
    "does not define the cohort. Realized-only: a trade appears the day AFTER "
    "it exits, so the live cohort reads one session behind the engine's own "
    'public panel. Pass policy_version="all" for every era, but read '
    "DISOWNED_COHORT_NOTE first. " + _PAPER_DISCLAIMER
)

# The escape hatch is NOT a track record. Cohort resets happen because the
# engine has repudiated the selection that produced those rows, so "all" mixes
# live receipts with rows the engine no longer stands behind. Saying only
# "exit mechanics differ" reads as a methodology nuance and undersells it.
DISOWNED_COHORT_NOTE = (
    "This is NOT the live cohort. Any non-live policy_version filter "
    '(including "all") reaches cohorts the engine has DISOWNED, not just '
    "older exit mechanics. Resets: 2026-06-26 (live-OI floor), 2026-07-29 "
    "(tournament liquidity upgrade), 2026-08-10 (stale-day-bar fix — the "
    "2026-07-29 cohort's primary print floor never actually fired, and two of "
    "its picks were selected on a phantom liquidity count), 2026-08-13 "
    "(fail-soft restore can never become the pick — two of the 2026-08-10 "
    "cohort's three entries were restores the new selection cannot make). "
    "Rows before 2026-08-13 are NOT the live track record and must not be "
    "aggregated into one. " + _PAPER_DISCLAIMER
)

# --- Firestore collections --------------------------------------------------
DAILY_REPORTS_COLLECTION = "daily_reports"


# --- singleton clients ------------------------------------------------------
try:
    BQ: bigquery.Client | None = bigquery.Client(project=PROJECT_ID)
except Exception as e:  # noqa: BLE001
    logger.error("data: BigQuery client init failed: %s", e)
    BQ = None

try:
    FS: firestore.Client | None = firestore.Client(project=PROJECT_ID)
except Exception as e:  # noqa: BLE001
    logger.error("data: Firestore client init failed: %s", e)
    FS = None
