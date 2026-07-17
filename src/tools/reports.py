"""
Daily report tools for GammaRips MCP
"""

import logging
from typing import Any

from google.cloud import firestore

from utils.data import DAILY_REPORTS_COLLECTION
from utils.data import FS as db
from utils.safety import clamp, safe_error

logger = logging.getLogger(__name__)


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
        reports_ref = db.collection(DAILY_REPORTS_COLLECTION)

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
        return {"error": safe_error(e, "get_daily_report")}


def get_report_list(limit: int = 10) -> list[dict[str, Any]]:
    """
    List available reports, most recent first. Repeated titles across dates
    are deduplicated (the generator occasionally reuses a headline) — each
    title appears once, at its most recent scan_date.

    Args:
        limit: Number of reports to return (default 10).

    Returns:
        List of {scan_date, title, created_at}.
    """
    if not db:
        return [{"error": "Firestore client not initialized"}]

    limit = clamp(limit, 1, 30, default=10)

    try:
        reports_ref = db.collection(DAILY_REPORTS_COLLECTION)
        # Over-fetch, then dedupe titles keeping the most recent occurrence.
        query = reports_ref.order_by("scan_date", direction=firestore.Query.DESCENDING).limit(
            min(limit * 3, 90)
        )

        results = []
        seen_titles: set[str] = set()
        for doc in query.stream():
            data = doc.to_dict()
            title = data.get("title")
            if title in seen_titles:
                continue
            seen_titles.add(title)
            results.append(
                {
                    "scan_date": data.get("scan_date"),
                    "title": title,
                    "created_at": data.get("created_at"),
                }
            )
            if len(results) >= limit:
                break

        return results

    except Exception as e:
        return [{"error": safe_error(e, "get_report_list")}]
