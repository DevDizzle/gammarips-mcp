"""
Metadata tools for GammaRips MCP
"""

import logging
from typing import Any

from google.cloud import bigquery

logger = logging.getLogger(__name__)

# Initialize client
try:
    client = bigquery.Client(project="profitscout-fida8")
except Exception as e:
    logger.error(f"Failed to initialize BigQuery client: {e}")
    client = None


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
        logger.error(f"Error in get_available_dates: {e}")
        return [{"error": str(e)}]


def get_enriched_signal_schema() -> list[dict[str, Any]]:
    """
    Returns the column schema of overnight_signals_enriched (BigQuery). Chat
    agents use this to introspect which fields are available when answering
    open-ended "why this pick?" questions without hallucinating field names.

    Returns:
        List of {column_name, data_type, is_nullable}.
    """
    if not client:
        return [{"error": "BigQuery client not initialized"}]

    try:
        query = """
            SELECT column_name, data_type, is_nullable
            FROM `profitscout-fida8.profit_scout.INFORMATION_SCHEMA.COLUMNS`
            WHERE table_name = 'overnight_signals_enriched'
            ORDER BY ordinal_position
        """
        results = []
        for row in client.query(query).result():
            results.append(
                {
                    "column_name": row.column_name,
                    "data_type": row.data_type,
                    "is_nullable": row.is_nullable,
                }
            )
        return results

    except Exception as e:
        logger.error(f"Error in get_enriched_signal_schema: {e}")
        return [{"error": str(e)}]
