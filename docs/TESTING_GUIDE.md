# GammaRips MCP Server: Testing Guide

This guide provides instructions for testing the GammaRips MCP server, both locally and after deployment to Cloud Run.

---

## 1. Local Testing with Python Client

You can test the server locally using the `mcp` Python client library. This is the best way to perform unit and integration tests on the tools.

### 1.1. Create a Test Script

Create a file named `test_client.py` in the root of the project:

```python
# test_client.py

import asyncio
import json

from mcp.client.fastmcp import Client


async def run_tests():
    """Connect to the local MCP server and test its tools."""
    server_url = "http://127.0.0.1:8080"
    print(f"Connecting to MCP server at {server_url}...")

    try:
        async with Client(transport="http", url=server_url) as client:
            print("Connection successful!")

            # Discover available tools
            tools = await client.tools.list()
            print(f"Discovered {len(tools)} tools:")
            for tool in tools:
                print(f"  - {tool.name}: {tool.description}")
            print("\n" + "-"*20 + "\n")

            # Test 1: get_winners_dashboard
            print("Testing get_winners_dashboard...")
            result_json = await client.tools.call(
                "get_winners_dashboard", limit=3, option_type="CALL"
            )
            result = json.loads(result_json)
            print(f"Found {result.get("count")} winners.")
            print(json.dumps(result, indent=2))
            print("\n" + "-"*20 + "\n")

            # Test 2: get_options_signals for a specific ticker
            ticker = "AAPL"
            print(f"Testing get_options_signals for {ticker}...")
            result_json = await client.tools.call("get_options_signals", ticker=ticker)
            result = json.loads(result_json)
            print(f"Found {result.get("count")} signals for {ticker}.")
            print(json.dumps(result, indent=2))
            print("\n" + "-"*20 + "\n")

            # Test 3: get_stock_analysis
            ticker = "NVDA"
            print(f"Testing get_stock_analysis for {ticker}...")
            result_json = await client.tools.call(
                "get_stock_analysis", ticker=ticker, include_sections=["technicals", "news"]
            )
            result = json.loads(result_json)
            print(f"Successfully fetched analysis for {ticker}.")
            print(json.dumps(result, indent=2))
            print("\n" + "-"*20 + "\n")

    except Exception as e:
        print(f"An error occurred: {e}")


if __name__ == "__main__":
    asyncio.run(run_tests())

```

### 1.2. Run the Test

1.  **Start the MCP server** in one terminal:
    ```bash
    python src/server.py
    ```

2.  **Run the test client** in another terminal:
    ```bash
    python test_client.py
    ```

You should see the output of each tool call, confirming that the server is working correctly.

---

## 2. Testing the Deployed Cloud Run Service

After deploying the service to Cloud Run, you can test it remotely.

### 2.1. Using the Cloud Run Proxy (Recommended)

The `gcloud` CLI provides a secure proxy that forwards a local port to your remote Cloud Run service. This is the most secure way to test, as it uses your GCP credentials for authentication.

1.  **Start the proxy**:
    ```bash
    gcloud run services proxy gammarips-mcp --region=us-central1
    ```
    This will start a proxy on `http://127.0.0.1:8080`.

2.  **Run the same `test_client.py` script** as in the local testing section. It will connect to the local proxy, which will securely forward the requests to your Cloud Run service.

### 2.2. Testing with a Public URL and API Key (Phase 2)

Once you have enabled API key authentication and deployed the service with `--allow-unauthenticated`, you can test it using its public URL.

1.  **Get the service URL** from the Cloud Run console or by running:
    ```bash
    gcloud run services describe gammarips-mcp --region=us-central1 --format=\"value(status.url)\"
    ```

2.  **Update `test_client.py`** to include the API key in the headers:

    ```python
    # test_client_api_key.py
    
    # ... (imports)
    
    async def run_tests():
        server_url = "<your-cloud-run-service-url>"
        api_key = "<your-generated-api-key>"
        headers = {"X-API-Key": api_key}
    
        async with Client(transport="http", url=server_url, headers=headers) as client:
            # ... (rest of the test script)
    
    # ... (main block)
    ```

3.  **Run the script**:
    ```bash
    python test_client_api_key.py
    ```

This will test the full authentication flow of your production-ready TaaS platform.
