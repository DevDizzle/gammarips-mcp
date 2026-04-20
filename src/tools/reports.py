"""
Daily report tools for GammaRips MCP
"""

import logging
from typing import Any

from google.cloud import firestore

logger = logging.getLogger(__name__)

# Initialize client
try:
    db = firestore.Client(project="profitscout-fida8")
except Exception as e:
    logger.error(f"Failed to initialize Firestore client: {e}")
    db = None


def get_daily_report(date: str | None = None) -> dict[str, Any]:
    """
    Returns the full daily intelligence report.

    Args:
        date: Filter by date (YYYY-MM-DD). Defaults to most recent.

    Returns:
        Full report with title, content (markdown), created_at, scan_date.
    """
    if not db:
        return {"error": "Firestore client not initialized"}

    try:
        reports_ref = db.collection("daily_reports")

        if date:
            query = reports_ref.where("scan_date", "==", date).limit(1)
            docs = query.stream()
            for doc in docs:
                return doc.to_dict()
            return {"error": f"No report found for date {date}"}
        else:
            # Get most recent
            query = reports_ref.order_by("scan_date", direction=firestore.Query.DESCENDING).limit(1)
            docs = query.stream()
            for doc in docs:
                return doc.to_dict()
            return {"error": "No reports found"}

    except Exception as e:
        logger.error(f"Error in get_daily_report: {e}")
        return {"error": str(e)}


def get_report_list(limit: int = 10) -> list[dict[str, Any]]:
    """
    List available reports.

    Args:
        limit: Number of reports to return (default 10).

    Returns:
        List of {scan_date, title, created_at}.
    """
    if not db:
        return [{"error": "Firestore client not initialized"}]

    try:
        reports_ref = db.collection("daily_reports")
        query = reports_ref.order_by("scan_date", direction=firestore.Query.DESCENDING).limit(limit)

        results = []
        for doc in query.stream():
            data = doc.to_dict()
            results.append(
                {
                    "scan_date": data.get("scan_date"),
                    "title": data.get("title"),
                    "created_at": data.get("created_at"),
                }
            )

        return results

    except Exception as e:
        logger.error(f"Error in get_report_list: {e}")
        return [{"error": str(e)}]
