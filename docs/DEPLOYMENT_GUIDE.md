# GammaRips MCP Server: Deployment Guide

**Date:** January 4, 2026  
**Author:** Manus AI

This guide walks you through deploying the GammaRips MCP Server to Google Cloud Run and connecting it to AI agents for testing.

---

## Prerequisites

Before you begin, ensure you have the following:

1.  **Google Cloud Platform Account** with an active project (e.g., `gammarips-lx6bb`).
2.  **Google Cloud SDK** installed and configured on your local machine.
3.  **Owner or Editor permissions** in your GCP project.
4.  **Enabled APIs**: Cloud Run, Cloud Build, Artifact Registry, BigQuery, Cloud Storage, Firestore.
5.  **Existing GammaRips data** in BigQuery and Google Cloud Storage.

---

## Phase 1: Deploy MVP to Cloud Run

This phase focuses on deploying the MCP server without authentication, allowing you to test it internally with Manus AI or other MCP clients.

### Step 1: Clone the Repository

If you haven't already, clone the `gammarips-mcp` repository to your local machine:

```bash
git clone <repository_url>
cd gammarips-mcp
```

### Step 2: Configure Environment Variables

The deployment script and Cloud Run service rely on environment variables to connect to your GCP resources. Review the `.env.example` file and ensure the following values are correct:

*   `GCP_PROJECT_ID`: Your GCP project ID (e.g., `gammarips-lx6bb`).
*   `GCP_REGION`: The region where you want to deploy (e.g., `us-central1`).
*   `BIGQUERY_DATASET`: The BigQuery dataset containing your GammaRips tables (e.g., `profit_scout`).
*   `GCS_BUCKET_NAME`: The GCS bucket containing your analysis files (e.g., `profit-scout-data`).

These values are already set in the `deploy.sh` script, but you can override them by exporting environment variables before running the script.

### Step 3: Authenticate with Google Cloud

Log in to your GCP account:

```bash
gcloud auth login
```

Set your active project:

```bash
gcloud config set project gammarips-lx6bb
```

### Step 4: Run the Deployment Script

The `deploy.sh` script automates the entire deployment process. It will:

1.  Create an Artifact Registry repository (if it doesn't exist).
2.  Build the Docker image using Cloud Build.
3.  Push the image to Artifact Registry.
4.  Deploy the image to Cloud Run.

Run the script:

```bash
./scripts/deploy.sh
```

The script will output the service URL upon completion. It should look something like:

```
https://gammarips-mcp-abcdefgh-uc.a.run.app
```

**Note**: The service is deployed with `--allow-unauthenticated`, meaning anyone with the URL can access it. This is acceptable for Phase 1 internal testing, but you will need to enable authentication for the public launch in Phase 2.

### Step 5: Test the Deployed Service

You can test the deployed service using the Cloud Run proxy, which creates a secure, authenticated tunnel to your service.

1.  **Start the proxy**:
    ```bash
    gcloud run services proxy gammarips-mcp --region=us-central1
    ```
    This will start a local proxy on `http://127.0.0.1:8080`.

2.  **Run the test client** (see `docs/TESTING_GUIDE.md` for details):
    ```bash
    python test_client.py
    ```

If the tests pass, your MCP server is successfully deployed and operational.

---

## Phase 2: Enable Authentication and Launch Publicly

Once you have validated the MVP, you can enable API key authentication to launch the service publicly and start monetizing it.

### Step 1: Set Up Firestore for User Management

1.  **Enable Firestore** in your GCP project (if not already enabled).
2.  **Create a collection** named `taas_users` in Firestore. This collection will store user profiles and API keys.
3.  **Create a collection** named `usage_logs` for tracking tool usage.

### Step 2: Generate API Keys for Test Users

Use the `api_key_generator.py` script to generate API keys for your initial users:

```bash
python src/auth/api_key_generator.py
```

This will output an API key and its hash. Store the hash in a Firestore document in the `taas_users` collection with the following structure:

```json
{
  "email": "user@example.com",
  "api_key_hash": "<generated_hash>",
  "plan": "paid",
  "subscription_status": "active",
  "usage_count": 0,
  "created_at": "<timestamp>",
  "updated_at": "<timestamp>"
}
```

Give the plain-text API key to the user. **Never store the plain-text key in Firestore.**

### Step 3: Enable Authentication in the Server

1.  **Edit `src/server.py`** and uncomment the authentication code block. This will wrap all tools with the `authenticated_tool` decorator.
2.  **Update the `.env` file** or Cloud Run environment variables to set `REQUIRE_API_KEY=true`.

### Step 4: Redeploy the Service

Run the deployment script again to deploy the updated server with authentication enabled:

```bash
./scripts/deploy.sh
```

### Step 5: Test with API Key

Update your test client to include the API key in the headers (see `docs/TESTING_GUIDE.md` for the full example):

```python
headers = {"X-API-Key": "ps_live_<your_key>"}
async with Client(transport="http", url=server_url, headers=headers) as client:
    # ... test code
```

Run the test to confirm that authentication is working correctly.

---

## Phase 3: Connect to AI Agents

Once the server is deployed and tested, you can connect it to AI agents.

### Connecting to Manus AI

1.  Open Manus AI and navigate to the MCP server configuration.
2.  Add a new MCP server with the following details:
    *   **Server URL**: `<your-cloud-run-service-url>`
    *   **Authentication**: API Key
    *   **Header Name**: `X-API-Key`
    *   **API Key**: `<your-generated-api-key>`
3.  Save the configuration. Manus AI will connect to the server and discover the available tools.
4.  Test by asking Manus: "What are the best options plays today?"

### Connecting to ChatGPT (Custom GPT)

1.  In ChatGPT, create a new Custom GPT.
2.  In the "Actions" section, add a new action with the following OpenAPI schema (you can generate this from the MCP server's tool definitions).
3.  Set the authentication to "API Key" and provide the header name and key.
4.  Test the custom GPT by asking it to fetch options signals.

### Connecting to Claude Desktop

1.  Open Claude Desktop and navigate to the Custom Connectors settings.
2.  Add a new connector with your Cloud Run service URL and API key.
3.  Claude will connect and discover the tools.
4.  Test by asking Claude for stock analysis.

---

## Monitoring and Maintenance

### Viewing Logs

You can view the server logs in the Google Cloud Console:

1.  Navigate to **Cloud Run** > **gammarips-mcp** > **Logs**.
2.  Filter by severity (INFO, WARNING, ERROR) to troubleshoot issues.

### Monitoring Usage

Once authentication is enabled, you can monitor usage by querying the `usage_logs` collection in Firestore. This data can be used for billing and analytics.

### Scaling

Cloud Run automatically scales the service based on incoming traffic. You can configure the maximum number of instances in the `scripts/deploy.sh` script (currently set to 10).

---

## Troubleshooting

### Issue: "Request validation failed" (ValueError) or HTTP 421

**Cause**: The `FastMCP` server defaults to `host="127.0.0.1"`, which enables strict DNS rebinding protection. Cloud Run requests come from a proxy with a different Host header, causing validation to fail.

**Solution**: Ensure `FastMCP` is initialized with `host="0.0.0.0"` in `src/server.py`. This disables the strict localhost checks and allows traffic from the Cloud Run proxy.

### Issue: "Permission Denied" when accessing BigQuery or GCS

**Solution**: Ensure that the Cloud Run service account has the necessary IAM roles:

*   `roles/bigquery.dataViewer` for reading BigQuery tables.
*   `roles/storage.objectViewer` for reading GCS objects.

You can grant these roles in the IAM & Admin section of the GCP Console.

### Issue: "API key is invalid"

**Solution**: Verify that the API key hash in Firestore matches the hash of the key you are using. You can regenerate the hash using the `api_key_generator.py` script.

### Issue: "No data found for ticker"

**Solution**: Ensure that the enrichment and serving pipelines have run for the requested date. Check the `run_date` partitions in BigQuery and GCS.

---

## Next Steps

Congratulations! You have successfully deployed the GammaRips MCP Server. The next steps are:

1.  **Build the user registration and billing system** (Phase 2) using Next.js and Firebase.
2.  **Integrate Stripe** for subscription management.
3.  **Create public documentation** for users to connect their AI agents.
4.  **Launch marketing campaigns** to attract users.

Refer to the [TaaS Strategy Document](../GammaRips_TaaS_Strategy.md) for the full roadmap.
