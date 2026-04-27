"""
Metadata tools for GammaRips MCP
"""

import logging
from typing import Any

from google.cloud import bigquery

from utils.safety import safe_error

logger = logging.getLogger(__name__)

# Initialize client
try:
    client = bigquery.Client(project="profitscout-fida8")
except Exception as e:
    logger.error(f"Failed to initialize BigQuery client: {e}")
    client = None


# Whitelist of public-safe columns for `get_enriched_signal_schema`. Future
# internal-only columns added to overnight_signals_enriched (debug fields,
# experimental cohort tags, vendor PII, etc.) won't auto-leak via the schema
# tool — they have to be added here explicitly.
_PUBLIC_SCHEMA_COLUMNS: tuple[str, ...] = (
    "scan_date",
    "ticker",
    "direction",
    "overnight_score",
    "volume_oi_ratio",
    "moneyness_pct",
    "recommended_contract",
    "recommended_strike",
    "recommended_expiration",
    "recommended_mid_price",
    "recommended_dte",
    "recommended_spread_pct",
    "call_dollar_volume",
    "put_dollar_volume",
    "key_headline",
    "vix3m_at_enrich",
    "vix_now_at_decision",
    "is_premium_signal",
)


def get_available_dates() -> list[dict[str, Any]]:
    """
    Returns which scan dates have data available.

    Returns:
        List of {scan_date, signal_count}
    """
    if not client:
        return [{"error": "BigQuery client not initialized"}]

    try:
        query = """
            SELECT
                scan_date,
                COUNT(*) as signal_count
            FROM `profitscout-fida8.profit_scout.overnight_signals`
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


def get_enriched_signal_schema() -> list[dict[str, Any]]:
    """
    Returns the column schema of overnight_signals_enriched (BigQuery), filtered
    to a whitelist of public-safe columns. Chat agents use this to introspect
    available fields when answering "why this pick?" questions without
    hallucinating field names.

    Future internal columns added to the underlying table do NOT auto-leak via
    this tool — they must be added explicitly to `_PUBLIC_SCHEMA_COLUMNS`.

    Returns:
        List of {column_name, data_type, is_nullable}, ordered by ordinal_position.
    """
    if not client:
        return [{"error": "BigQuery client not initialized"}]

    try:
        query = """
            SELECT column_name, data_type, is_nullable
            FROM `profitscout-fida8.profit_scout.INFORMATION_SCHEMA.COLUMNS`
            WHERE table_name = 'overnight_signals_enriched'
              AND column_name IN UNNEST(@allowed)
            ORDER BY ordinal_position
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("allowed", "STRING", list(_PUBLIC_SCHEMA_COLUMNS)),
            ]
        )
        results = []
        for row in client.query(query, job_config=job_config).result():
            results.append(
                {
                    "column_name": row.column_name,
                    "data_type": row.data_type,
                    "is_nullable": row.is_nullable,
                }
            )
        return results

    except Exception as e:
        return [{"error": safe_error(e, "get_enriched_signal_schema")}]
