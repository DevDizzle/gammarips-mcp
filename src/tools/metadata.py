"""
Metadata tools for GammaRips MCP.

`get_enriched_signal_schema` serves the substrate's MACHINE-READABLE column
classification: every column of the outcome/label table carries a description
of the form `[classification | as-of BOUNDARY] text`, with classification in
{feature, label, opportunity, regime_telemetry, identity}. An agent can (and
should) refuse to use any non-`feature` column as a selection input — see
get_playbook("leakage-and-data-contract").
"""

import logging
import re
from typing import Any

from utils.data import BQ as client
from utils.data import DATASET_FQN
from utils.data import RAW_SCAN_TABLE as _RAW_SCAN
from utils.safety import redact, safe_error

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(
    r"^\[(?P<classification>feature|label|opportunity|regime_telemetry|identity)"
    r"\s*\|\s*as-of\s*(?P<as_of>[^\]]+)\]\s*(?P<text>.*)$",
    re.IGNORECASE | re.DOTALL,
)

_VOCABULARY = {
    "identity": "Join keys / contract spec. Known as-of <= scan_date. Not signals.",
    "feature": (
        "Point-in-time inputs, known as-of <= scan_date (the selection point). "
        "The ONLY class safe to use in selection logic."
    ),
    "label": "Realized bracket outcomes (post-entry). Predict these; never condition on them.",
    "opportunity": (
        "Exit-free realized excursions (opp_* MFE/MAE surface, post-entry). "
        "Research surface, not a feature."
    ),
    "regime_telemetry": (
        "Entry-day-close regime values (oc_*), realized AFTER the same-day "
        "trade. Telemetry only — using them as features is lookahead."
    ),
}


def get_available_dates() -> list[dict[str, Any]]:
    """
    Returns which scan dates have data available.

    Returns:
        List of {scan_date, signal_count}
    """
    if not client:
        return [{"error": "BigQuery client not initialized"}]

    try:
        query = f"""
            SELECT
                scan_date,
                COUNT(*) as signal_count
            FROM {_RAW_SCAN}
            GROUP BY scan_date
            ORDER BY scan_date DESC
            LIMIT 30
        """

        query_job = client.query(query)

        results = []
        for row in query_job.result():
            results.append({"scan_date": str(row.scan_date), "signal_count": row.signal_count})

        return results

    except Exception as e:
        return [{"error": safe_error(e, "get_available_dates")}]


def get_enriched_signal_schema() -> dict[str, Any]:
    """
    RESEARCH / POWER-USER tool. If you just need what a field MEANS,
    `get_signal_explainer` is the everyday path — this is the formal contract
    for grounding research code.

    The substrate DATA CONTRACT, machine-readable: every column of the
    outcome/label substrate with its leakage classification and as-of
    boundary, plus the exact column set exposed by the point-in-time features
    view (what `get_pool_features` serves).

    Classifications: identity | feature | label | opportunity |
    regime_telemetry. Only `feature` columns are safe as selection inputs —
    everything else is realized after the selection point. Use this tool to
    ground research code instead of hallucinating field names, and see
    get_playbook("leakage-and-data-contract") for the rules in prose.

    Returns:
        {vocabulary, features_view_columns: [...],
         columns: [{column, data_type, classification, as_of, description}]}
    """
    if not client:
        return {"error": "BigQuery client not initialized"}

    try:
        class_query = f"""
            SELECT p.column_name, c.data_type, p.description
            FROM `{DATASET_FQN}.INFORMATION_SCHEMA.COLUMN_FIELD_PATHS` p
            JOIN `{DATASET_FQN}.INFORMATION_SCHEMA.COLUMNS` c
              ON c.table_name = p.table_name AND c.column_name = p.column_name
            WHERE p.table_name = 'enriched_option_outcomes'
            ORDER BY c.ordinal_position
        """
        columns = []
        for row in client.query(class_query).result():
            desc = row.description or ""
            m = _TAG_RE.match(desc)
            columns.append(
                {
                    "column": row.column_name,
                    "data_type": row.data_type,
                    "classification": m.group("classification").lower() if m else "untagged",
                    "as_of": m.group("as_of").strip() if m else None,
                    "description": redact(m.group("text").strip() if m else desc),
                }
            )

        view_query = f"""
            SELECT column_name
            FROM `{DATASET_FQN}.INFORMATION_SCHEMA.COLUMNS`
            WHERE table_name = 'enriched_features_v1'
            ORDER BY ordinal_position
        """
        view_cols = [row.column_name for row in client.query(view_query).result()]

        return {
            "vocabulary": _VOCABULARY,
            "features_view_columns": view_cols,
            "features_view_note": (
                "The allowlist view served by get_pool_features — the only "
                "columns that may feed selection logic. Columns classified "
                "'feature' below but absent here are pending allowlist "
                "activation and will appear automatically once classified in."
            ),
            "columns": columns,
        }

    except Exception as e:
        return {"error": safe_error(e, "get_enriched_signal_schema")}
