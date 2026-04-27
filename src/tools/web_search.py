import logging
import os

import requests

from utils.safety import clamp, safe_error

logger = logging.getLogger(__name__)

# Caller-supplied query strings hit a paid Google Custom Search API. Cap the
# query length to defend against memory-amplification + cost attacks.
_MAX_QUERY_LEN = 500


def web_search(query: str, num_results: int = 5) -> str:
    """
    Performs a Google Web Search using the Custom Search JSON API via direct HTTP requests.
    Useful for finding real-time information, news, or verifying facts (grounding).

    Args:
        query: The search query string.
        num_results: Number of results to return (default 5, max 10).

    Returns:
        A formatted string containing the top search results (Title, Snippet, Link).
    """
    api_key = os.getenv("GOOGLE_API_KEY")
    cse_id = os.getenv("GOOGLE_CSE_ID")

    if not api_key or not cse_id:
        return "Error: GOOGLE_API_KEY or GOOGLE_CSE_ID not configured in environment."

    # Bound caller-controlled inputs before they reach the paid Google CSE API.
    query = (query or "")[:_MAX_QUERY_LEN]
    num = clamp(num_results, 1, 10, default=5)

    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "key": api_key,
        "cx": cse_id,
        "q": query,
        "num": num,
    }

    try:
        response = requests.get(url, params=params, timeout=10)

        if response.status_code == 403:
            logger.error(f"Web Search 403 Forbidden: {response.text}")
            return "Error: 403 Forbidden. Please check your GOOGLE_API_KEY and GOOGLE_CSE_ID."

        response.raise_for_status()
        data = response.json()

        items = data.get("items", [])

        if not items:
            return f"No results found for query: '{query}'"

        # Format results for the LLM
        formatted_results = []
        for i, item in enumerate(items, 1):
            title = item.get("title", "No Title")
            snippet = item.get("snippet", "No Snippet")
            link = item.get("link", "No Link")
            source = item.get("displayLink", "Unknown Source")

            formatted_results.append(
                f"Result {i}:\nSource: {source}\nTitle: {title}\nURL: {link}\nSummary: {snippet}\n"
            )

        return "\n---\n".join(formatted_results)

    except requests.exceptions.RequestException as e:
        return safe_error(e, "web_search")
    except Exception as e:
        return safe_error(e, "web_search")
