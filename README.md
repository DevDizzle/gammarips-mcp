# GammaRips MCP Server

Agent-first options trading intelligence for overnight and pre-market setups.

GammaRips exposes a free hosted MCP server for querying overnight options-flow signals, enriched ticker analysis, performance tracking, and daily market intelligence reports.

## Hosted MCP endpoint

- **SSE:** `https://gammarips-mcp-406581297632.us-central1.run.app/sse`
- **JSON-RPC:** `https://gammarips-mcp-406581297632.us-central1.run.app/jsonrpc`
- **Server card:** `https://gammarips-mcp-406581297632.us-central1.run.app/.well-known/mcp/server-card.json`
- **Auth:** none

## Available tools

- `get_overnight_signals` — raw overnight scanner output by date, direction, ticker, or minimum score
- `get_enriched_signals` — AI-enriched high-conviction setups with technical and catalyst context
- `get_signal_detail` — deep dive on one ticker’s signal
- `get_signal_performance` — historical outcome tracking for prior signals
- `get_win_rate_summary` — aggregate win-rate / return summary over a lookback window
- `get_daily_report` — latest full daily intelligence report
- `get_report_list` — list available reports
- `get_available_dates` — list dates with available scan data
- `web_search` — lightweight live web search for additional context

## Quick connect

### OpenClaw / generic MCP config

```json
{
  "mcpServers": {
    "gammarips": {
      "url": "https://gammarips-mcp-406581297632.us-central1.run.app/sse",
      "transport": "sse"
    }
  }
}
```

### Claude Desktop / other local-client style config

If your client supports remote SSE servers, use the hosted endpoint above. If it only supports local stdio processes, run the server locally and point your client at that wrapper process.

## Local development

### Prerequisites

- Python 3.10+
- Optional: Docker

### Setup

```bash
git clone https://github.com/DevDizzle/gammarips-mcp.git
cd gammarips-mcp
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

### Run locally

```bash
PYTHONPATH=src python src/server.py
```

The server binds to `0.0.0.0:${PORT:-8080}` and serves MCP over SSE.

### Docker

```bash
docker build -t gammarips-mcp .
docker run --rm -p 8080:8080 --env-file .env gammarips-mcp
```

## Environment

See `.env.example` for the current environment variables. Typical values include:

- `GCP_PROJECT_ID`
- `FIRESTORE_DATABASE`
- `GCS_BUCKET_NAME`
- `LOG_LEVEL`
- `PORT`

## Validation

### Python compile check

```bash
python -m compileall src
```

### Docker build check

```bash
docker build -t gammarips-mcp:test .
```

## Deployment

The repo includes a GitHub Actions workflow for deploying to Cloud Run on pushes to `main`.

## License

MIT
