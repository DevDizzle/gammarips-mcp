"""
Google Cloud Storage client for accessing GammaRips analysis files
"""

import json
import logging
import os
import re
from datetime import datetime
from typing import Any

from google.cloud import storage

logger = logging.getLogger(__name__)


class GCSClient:
    """Client for reading GammaRips analysis files from Google Cloud Storage."""

    _client_instance = None
    _bucket_instance = None

    def __init__(self):
        self.project_id = os.getenv("GCP_PROJECT_ID")
        self.bucket_name = os.getenv("GCS_BUCKET_NAME")

        if GCSClient._client_instance is None:
            GCSClient._client_instance = storage.Client(project=self.project_id)
            GCSClient._bucket_instance = GCSClient._client_instance.bucket(self.bucket_name)
            logger.info(f"Initialized GCS client for bucket: {self.bucket_name}")

        self.client = GCSClient._client_instance
        self.bucket = GCSClient._bucket_instance

    def _get_latest_file_from_prefix(
        self, prefix: str, ticker: str, extension: str = ".json"
    ) -> str | None:
        """Find the latest file for a ticker in a specific prefix based on date in filename.

        Expected format: {prefix}/{ticker}_{date}{extension} or similar.
        """
        try:
            # List blobs with the specific prefix
            blobs = self.client.list_blobs(self.bucket_name, prefix=prefix)

            latest_date = None
            latest_blob_name = None

            # Regex to find date in filename (YYYY-MM-DD)
            # Matches: Ticker_2026-01-04.json or Ticker_recommendation_2026-01-04.md
            date_pattern = re.compile(r"(\d{4}-\d{2}-\d{2})")

            for blob in blobs:
                if ticker.upper() in blob.name and blob.name.endswith(extension):
                    match = date_pattern.search(blob.name)
                    if match:
                        date_str = match.group(1)
                        try:
                            file_date = datetime.strptime(date_str, "%Y-%m-%d")
                            if latest_date is None or file_date > latest_date:
                                latest_date = file_date
                                latest_blob_name = blob.name
                        except ValueError:
                            continue

            return latest_blob_name
        except Exception as e:
            logger.error(f"Error finding latest file in {prefix} for {ticker}: {e}")
            return None

    def _read_json_blob(self, blob_path: str) -> dict[str, Any] | None:
        """Read a JSON file from GCS, handling potential Markdown formatting."""
        try:
            blob = self.bucket.blob(blob_path)
            if not blob.exists():
                logger.warning(f"Blob not found: {blob_path}")
                return None

            content = blob.download_as_text()

            # Clean Markdown code blocks if present
            # Matches ```json or ``` at start/end of content
            if content.strip().startswith("```"):
                # Remove first line (```json) and last line (```)
                content = re.sub(r"^```[a-zA-Z]*\n", "", content.strip())
                content = re.sub(r"\n```$", "", content.strip())

            return json.loads(content)
        except Exception as e:
            logger.error(f"Error reading blob {blob_path}: {e}")
            return None

    def _read_text_blob(self, blob_path: str) -> str | None:
        """Read a text/markdown file from GCS."""
        try:
            blob = self.bucket.blob(blob_path)
            if not blob.exists():
                logger.warning(f"Blob not found: {blob_path}")
                return None

            return blob.download_as_text()
        except Exception as e:
            logger.error(f"Error reading blob {blob_path}: {e}")
            return None

    async def get_technical_analysis(
        self, ticker: str, as_of: str = "latest"
    ) -> dict[str, Any] | None:
        """Get technical analysis for a ticker from GCS."""
        # Technicals are currently stored as just {TICKER}_technicals.json without a date
        # So we ignore the as_of parameter for now, or we could check metadata.

        blob_path = f"technicals-analysis/{ticker.upper()}_technicals.json"

        data = self._read_json_blob(blob_path)

        if data:
            return {
                "ticker": ticker.upper(),
                "as_of": as_of,
                "analysis": data,
            }
        else:
            return {
                "ticker": ticker.upper(),
                "as_of": as_of,
                "analysis": None,
                "message": f"No technical analysis found for {ticker.upper()}",
            }

    async def get_news_analysis(self, ticker: str, as_of: str = "latest") -> dict[str, Any] | None:
        """Get news analysis for a ticker from GCS."""
        if as_of == "latest":
            blob_path = self._get_latest_file_from_prefix("headline-news/", ticker, ".json")
        else:
            blob_path = f"headline-news/{ticker.upper()}_{as_of}.json"

        if not blob_path:
            return {"ticker": ticker.upper(), "message": "No news analysis found."}

        data = self._read_json_blob(blob_path)

        if data:
            return {
                "ticker": ticker.upper(),
                "as_of": as_of,
                "analysis": data,
            }
        else:
            return {
                "ticker": ticker.upper(),
                "as_of": as_of,
                "analysis": None,
                "message": f"No news analysis found for {ticker.upper()}",
            }

    async def get_fundamental_analysis(
        self, ticker: str, as_of: str = "latest"
    ) -> dict[str, Any] | None:
        """Get fundamental analysis for a ticker."""
        if as_of == "latest":
            blob_path = self._get_latest_file_from_prefix("fundamentals-analysis/", ticker, ".json")
        else:
            blob_path = f"fundamentals-analysis/{ticker.upper()}_{as_of}.json"

        if not blob_path:
            return {"ticker": ticker.upper(), "message": "No fundamental analysis found."}

        data = self._read_json_blob(blob_path)
        return {"ticker": ticker.upper(), "source": blob_path, "data": data}

    async def get_financial_analysis(
        self, ticker: str, as_of: str = "latest"
    ) -> dict[str, Any] | None:
        """Get financial analysis for a ticker."""
        if as_of == "latest":
            blob_path = self._get_latest_file_from_prefix("financials-analysis/", ticker, ".json")
        else:
            blob_path = f"financials-analysis/{ticker.upper()}_{as_of}.json"

        if not blob_path:
            return {"ticker": ticker.upper(), "message": "No financial analysis found."}

        data = self._read_json_blob(blob_path)
        return {"ticker": ticker.upper(), "source": blob_path, "data": data}

    async def get_business_summary(
        self, ticker: str, as_of: str = "latest"
    ) -> dict[str, Any] | None:
        """Get business summary for a ticker."""
        if as_of == "latest":
            blob_path = self._get_latest_file_from_prefix("business-summaries/", ticker, ".json")
        else:
            blob_path = f"business-summaries/{ticker.upper()}_{as_of}.json"

        if not blob_path:
            return {"ticker": ticker.upper(), "message": "No business summary found."}

        data = self._read_json_blob(blob_path)
        return {"ticker": ticker.upper(), "source": blob_path, "data": data}

    async def get_macro_thesis(self, as_of: str = "latest") -> dict[str, Any] | None:
        """Get the latest macro-economic thesis."""
        # Macro thesis might not be ticker specific.
        # Assuming format: macro-thesis/macro_thesis_{date}.json or similar.
        # Since _get_latest_file_from_prefix expects a ticker to be part of the name or query,
        # we might need to adjust or simply search for date pattern in the prefix.

        # For simplicity, let's assume a fixed naming convention or a dummy ticker "MACRO" if needed,
        # but better to just list and find latest.

        prefix = "macro-thesis/"
        try:
            blobs = self.client.list_blobs(self.bucket_name, prefix=prefix)

            latest_date = None
            latest_blob_name = None
            date_pattern = re.compile(r"(\d{4}-\d{2}-\d{2})")

            for blob in blobs:
                if blob.name.endswith(".json"):
                    match = date_pattern.search(blob.name)
                    if match:
                        date_str = match.group(1)
                        try:
                            file_date = datetime.strptime(date_str, "%Y-%m-%d")
                            # If as_of is a specific date, match it
                            if as_of != "latest" and date_str == as_of:
                                latest_blob_name = blob.name
                                break

                            if as_of == "latest":
                                if latest_date is None or file_date > latest_date:
                                    latest_date = file_date
                                    latest_blob_name = blob.name
                        except ValueError:
                            continue

            if not latest_blob_name:
                return {"message": "No macro thesis found."}

            data = self._read_json_blob(latest_blob_name)
            return {"source": latest_blob_name, "data": data}

        except Exception as e:
            logger.error(f"Error getting macro thesis: {e}")
            return {"error": str(e)}

    async def get_mda_analysis(self, ticker: str, as_of: str = "latest") -> dict[str, Any] | None:
        """Get MD&A analysis for a ticker."""
        if as_of == "latest":
            blob_path = self._get_latest_file_from_prefix("mda-analysis/", ticker, ".json")
        else:
            blob_path = f"mda-analysis/{ticker.upper()}_{as_of}.json"

        if not blob_path:
            return {"ticker": ticker.upper(), "message": "No MD&A analysis found."}

        data = self._read_json_blob(blob_path)
        return {"ticker": ticker.upper(), "source": blob_path, "data": data}

    async def get_transcript_analysis(
        self, ticker: str, as_of: str = "latest"
    ) -> dict[str, Any] | None:
        """Get earnings transcript analysis for a ticker."""
        if as_of == "latest":
            blob_path = self._get_latest_file_from_prefix("transcript-analysis/", ticker, ".json")
        else:
            blob_path = f"transcript-analysis/{ticker.upper()}_{as_of}.json"

        if not blob_path:
            return {"ticker": ticker.upper(), "message": "No transcript analysis found."}

        data = self._read_json_blob(blob_path)
        return {"ticker": ticker.upper(), "source": blob_path, "data": data}
