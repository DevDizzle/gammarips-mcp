from unittest.mock import MagicMock, patch

from tools.customer_service import get_support_policy

from tools.web_search import web_search

# --- Tests for Customer Service Tool ---


def test_get_support_policy_general():
    """Test retrieving general policy overview."""
    result = get_support_policy("general")
    assert "Core Principles" in result
    assert "Available FAQ Topics" in result


def test_get_support_policy_specific_topic():
    """Test retrieving a specific topic (e.g., 'financial advice')."""
    # The tool maps 'financial advice' -> "Is this financial advice?"
    result = get_support_policy("financial advice")
    assert "Is this financial advice?" in result
    assert "We are not financial advisors" in result


def test_get_support_policy_unknown_topic():
    """Test fallback for unknown topics."""
    result = get_support_policy("super obscure question")
    # Should fall back to full FAQ
    assert "Specific topic 'super obscure question' not found" in result
    assert "Common Questions & Answers" in result


# --- Tests for Web Search Tool ---


@patch("tools.web_search.build")
@patch("tools.web_search.os.getenv")
def test_web_search_success(mock_getenv, mock_build):
    """Test successful web search with mocked API."""
    # Setup mock env vars
    mock_getenv.side_effect = (
        lambda k: "fake_key" if k in ["GOOGLE_API_KEY", "GOOGLE_CSE_ID"] else None
    )

    # Setup mock API response
    mock_service = MagicMock()
    mock_resource = MagicMock()
    mock_service.cse.return_value = mock_resource

    mock_response = {
        "items": [
            {
                "title": "Test Result 1",
                "snippet": "This is a test snippet.",
                "link": "http://example.com/1",
                "displayLink": "example.com",
            },
            {
                "title": "Test Result 2",
                "snippet": "Another snippet.",
                "link": "http://example.com/2",
                "displayLink": "example.com",
            },
        ]
    }
    mock_resource.list.return_value.execute.return_value = mock_response
    mock_build.return_value = mock_service

    # Run tool
    result = web_search("test query")

    # Verify output format
    assert "Result 1:" in result
    assert "Title: Test Result 1" in result
    assert "Summary: This is a test snippet." in result
    assert "Result 2:" in result


@patch("tools.web_search.os.getenv")
def test_web_search_missing_config(mock_getenv):
    """Test web search fails gracefully without config."""
    mock_getenv.return_value = None
    result = web_search("test query")
    assert "Error: GOOGLE_API_KEY or GOOGLE_CSE_ID not configured" in result


@patch("tools.web_search.build")
@patch("tools.web_search.os.getenv")
def test_web_search_no_results(mock_getenv, mock_build):
    """Test web search handles empty results."""
    mock_getenv.return_value = "fake_key"

    mock_service = MagicMock()
    mock_resource = MagicMock()
    mock_service.cse.return_value = mock_resource
    mock_resource.list.return_value.execute.return_value = {"items": []}
    mock_build.return_value = mock_service

    result = web_search("weird query")
    assert "No results found" in result
