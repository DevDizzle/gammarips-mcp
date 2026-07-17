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
