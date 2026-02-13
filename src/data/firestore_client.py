"""
Firestore client for accessing GammaRips real-time data
"""

import logging
import os
from typing import Any, Dict, List, Optional
from datetime import datetime

from google.cloud import firestore

logger = logging.getLogger(__name__)


class FirestoreClient:
    """Client for querying GammaRips data from Firestore."""

    _client_instance = None

    def __init__(self):
        self.project_id = os.getenv("GCP_PROJECT_ID")
        
        # Singleton initialization
        if FirestoreClient._client_instance is None:
            FirestoreClient._client_instance = firestore.Client(project=self.project_id)
            logger.info(f"Initialized Firestore client for project: {self.project_id}")

        self.client = FirestoreClient._client_instance
        self.signals_collection = "overnight_signals"
        self.themes_collection = "market_themes"

    async def get_overnight_signals(
        self,
        date: str,
        direction: str = "ALL",
        min_score: int = 0,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Get overnight signals from Firestore.
        
        Args:
            date: YYYY-MM-DD string
            direction: BULLISH, BEARISH, or ALL
            min_score: Minimum overnight_score
            limit: Max results
            
        Returns:
            List of signal dictionaries
        """
        try:
            # Firestore query
            # Structure: overnight_signals/{date}/signals/{ticker} OR overnight_signals collection with date field
            # Assuming flattened collection or querying by date field based on spec:
            # "Data source: ... Firestore `overnight_signals` collection."
            
            # Implementation strategy: Query 'overnight_signals' collection where date == date
            # Note: Firestore requires composite indexes for multiple fields.
            
            collection_ref = self.client.collection(self.signals_collection)
            query = collection_ref.where("scan_date", "==", date)
            
            if direction != "ALL":
                query = query.where("direction", "==", direction)
                
            if min_score > 0:
                query = query.where("overnight_score", ">=", min_score)
                
            # Order by score desc (requires index with filters)
            query = query.order_by("overnight_score", direction=firestore.Query.DESCENDING)
            query = query.limit(limit)
            
            docs = query.stream()
            signals = []
            for doc in docs:
                sig = doc.to_dict()
                signals.append(sig)
                
            return signals

        except Exception as e:
            logger.error(f"Error querying Firestore signals: {e}")
            # Fallback to empty list so caller can try BigQuery
            return []

    async def get_signal_detail(self, ticker: str, date: str) -> Optional[Dict[str, Any]]:
        """Get detailed signal for a specific ticker and date."""
        try:
            # Try to find the specific document
            # Assuming ID is {date}_{ticker} or querying
            collection_ref = self.client.collection(self.signals_collection)
            query = collection_ref.where("scan_date", "==", date).where("ticker", "==", ticker).limit(1)
            docs = list(query.stream())
            
            if docs:
                return docs[0].to_dict()
            return None
            
        except Exception as e:
            logger.error(f"Error querying Firestore signal detail: {e}")
            return None

    async def get_market_themes(self, date: str) -> List[Dict[str, Any]]:
        """Get market themes for a date."""
        try:
            collection_ref = self.client.collection(self.themes_collection)
            # Assuming one document per date or multiple theme docs
            # If themes are stored as a list in a daily summary doc:
            query = collection_ref.where("scan_date", "==", date).limit(1)
            docs = list(query.stream())
            
            if docs:
                data = docs[0].to_dict()
                return data.get("themes", [])
            return []
            
        except Exception as e:
            logger.error(f"Error querying Firestore themes: {e}")
            return []
