# GammaRips MCP Server

Agent-first options trading intelligence for overnight and pre-market setups.

GammaRips exposes a free hosted MCP server for querying overnight options-flow signals, enriched ticker analysis, performance tracking, and daily market intelligence reports.

## Hosted MCP endpoint

- **SSE:** `https://gammarips-mcp-406581297632.us-central1.run.app/sse`
- **JSON-RPC:** `https://gammarips-mcp-406581297632.us-central1.run.app/jsonrpc`
- **Server card:** `https://gammarips-mcp-406581297632.us-central1.run.app/.well-known/mcp/server-card.json`
- **Auth:** none

## Available tools (18)

### Signal data
- `get_overnight_signals` — raw overnight scanner output by date, direction, ticker, or minimum score
- `get_enriched_signals` — AI-enriched high-conviction setups with technical and catalyst context
- `get_signal_detail` — deep dive on one ticker's signal
- `get_todays_pick` — V5.3 canonical daily pick (Firestore)
- `list_todays_picks` — last N days of canonical picks (includes skip-reason days)
- `get_freemium_preview` — top-N enriched signals, narrow fields (public/teaser)

### Performance / history
- `get_signal_performance` — outcome tracking from `signal_performance` (~30 signals/day)
- `get_win_rate_summary` — aggregate win rate from `signal_performance`
- `get_open_position` — current V5.3 trade status (pending pick, awaiting sim, last close)
- `get_position_history` — V5.3 realized bracket trades from `forward_paper_ledger`
- **`get_historical_performance`** — V5.3 ledger aggregate over a lookback (NEW 2026-04-27)

### Reports & metadata
- `get_daily_report` — latest full daily intelligence report
- `get_report_list` — list available reports
- `get_available_dates` — list dates with available scan data
- `get_enriched_signal_schema` — public-safe column schema (whitelisted)

### Reference / education (NEW 2026-04-27)
- **`get_market_calendar_status`** — NYSE open / next open / next close / holiday status
- **`get_signal_explainer`** — plain-English definition of any GammaRips field name

### External
- `web_search` — Google Custom Search (rate-limited, 10 req/min/IP)

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

## Security

See [`SECURITY.md`](./SECURITY.md) for the trust model — read-only guarantee,
parameterized-query SQL-injection defense, response-size bounds, per-IP rate
limits, sanitized errors, and schema whitelisting.

## License

MIT
