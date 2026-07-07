# GammaRips MCP Server

Options-flow intelligence **primitives** for AI agents.

Every trading morning GammaRips scans the US options market for unusual institutional activity and curates it hard — down to a ~50-name high-signal BULLISH pool. This MCP server gives a bring-your-own-agent trader that pool plus the substrate to reason over it: point-in-time features, realized **opportunity surfaces** (max-favorable / max-adverse excursions with no exit applied), bracket outcome labels, regime context, and methodology playbooks.

**Design principle: primitives, never a pick.** There is no "what should I buy" endpoint. Every agent reasons from the same data to its *own* contract and its *own* exit. Paper-traded research data; educational only; not investment advice.

## Hosted MCP endpoint

- **Streamable HTTP (primary):** `https://gammarips-mcp-406581297632.us-central1.run.app/mcp`
- **SSE (legacy, deprecation window):** `https://gammarips-mcp-406581297632.us-central1.run.app/sse`
- **Stateless JSON-RPC:** `https://gammarips-mcp-406581297632.us-central1.run.app/jsonrpc`
- **Server card:** `https://gammarips-mcp-406581297632.us-central1.run.app/.well-known/mcp/server-card.json`
- **Auth:** bearer-token tiering (Phase 2). Free-tier tools work with no key;
  pro tools need a GammaRips API key (`gr_live_...`) sent as
  `Authorization: Bearer <key>`. Currently in **shadow** rollout (nothing
  blocked yet); flips to enforce once keys are issued. Get one at
  [gammarips.com/pricing](https://gammarips.com/pricing).

## Available tools (25)

### Live pool

- `get_contract_snapshot` — fresh entry-day OI / session volume / last trade / day range for one contract (no quote fields on this data plan)
- `get_enriched_signals` — the curated daily candidate pool: enrichment narrative, technicals, catalyst, recommended contract, `mom_60` (leakage-safe view)
- `get_signal_detail` — full enrichment for one ticker
- `get_overnight_signals` — the raw pre-curation scan (wide net)
- `get_freemium_preview` — top-N teaser, narrow fields

### Research substrate (V3)
- `get_pool_features` — point-in-time feature vectors from the allowlist features view
- `get_opportunity_surface` — per-contract realized MFE/MAE excursions, exit-free (the core product surface)
- `query_outcomes` — row-level bracket labels (same-day GIGO or 3-day) joined to features
- `get_outcome_summary` — grouped aggregates (delta bucket, score, exit reason, ...) with honest exclusion counts
- `get_harvest_curve` — touch-probability curve (P(peak ≥ X) w/ CIs), day-of-peak buckets, stop-touch rates, live from the closed-window surface
- `estimate_exit_rule` — classify YOUR (target, stop) bracket against the surface; EV bounds, heuristic share reported
- `get_regime_context` — VIX/VIX3M/SPY-trend as-of scan date + the fail-closed rail

### Methodology
- `list_playbooks` / `get_playbook` — server-versioned playbooks: `start-here`, `daily-workflow`, `run-your-own-tournament`, `exit-lab`, `leakage-and-data-contract`, `changelog`. Also exposed as MCP resources (`gammarips://playbooks/{name}`).

### Performance / receipts
- `get_position_history` — the engine's realized paper trades (T+1 receipts; cohort-filtered, default live `V7_1_TILTED_GIGO`)
- `get_historical_performance` — cohort aggregate of the above
- `get_signal_performance` / `get_win_rate_summary` — UNDERLYING-stock direction outcomes for the broad pool (explicitly **not** option PnL)

### Reports & metadata
- `get_daily_report` / `get_report_list` — daily intelligence reports
- `get_available_dates` — scan dates with data
- `get_enriched_signal_schema` — the machine-readable data contract: every substrate column with its leakage classification (`feature | label | opportunity | regime_telemetry | identity`) and as-of boundary

### Reference / external
- `get_market_calendar_status` — NYSE calendar status
- `get_signal_explainer` — plain-English definition of any field (deterministic, no LLM)
- `web_search` — Google Custom Search (rate-limited, 10 req/min/IP)

### Removed in V3
`get_todays_pick`, `list_todays_picks`, `get_open_position` — the engine's own daily selection is no longer published same-day (realized receipts remain via `get_position_history`).

## Prompts

`morning_brief`, `analyze_candidate(ticker)`, `run_your_own_tournament` — thin orchestrations over the tools above. None returns a pick.

## Quick connect

### Claude Code

```bash
# Free tier (no key):
claude mcp add --transport http gammarips https://gammarips-mcp-406581297632.us-central1.run.app/mcp

# Pro (with your key):
claude mcp add --transport http gammarips https://gammarips-mcp-406581297632.us-central1.run.app/mcp \
  --header "Authorization: Bearer gr_live_your_key"
```

### Cursor

Settings → MCP → Add new MCP server, or add to `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "gammarips": {
      "url": "https://gammarips-mcp-406581297632.us-central1.run.app/mcp",
      "headers": { "Authorization": "Bearer gr_live_your_key" }
    }
  }
}
```

Omit `headers` for the free tier.

### Cline

MCP Servers → Remote Servers → Add, or add to `cline_mcp_settings.json`:

```json
{
  "mcpServers": {
    "gammarips": {
      "url": "https://gammarips-mcp-406581297632.us-central1.run.app/mcp",
      "type": "streamableHttp",
      "headers": { "Authorization": "Bearer gr_live_your_key" }
    }
  }
}
```

Omit `headers` for the free tier (8 anon tools).

### Generic MCP config

```json
{
  "mcpServers": {
    "gammarips": {
      "url": "https://gammarips-mcp-406581297632.us-central1.run.app/mcp"
    }
  }
}
```

Clients that only speak SSE can use the legacy `/sse` endpoint during the deprecation window.

Free tier works with no account: `get_daily_report`, `list_playbooks`/`get_playbook`, `get_signal_explainer`, `get_market_calendar_status`, `get_available_dates`, `get_report_list`, `get_freemium_preview`. Pro tools require Agent Access ($39/mo) — generate a key at [gammarips.com](https://gammarips.com/pricing).

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

The server binds to `0.0.0.0:${PORT:-8080}`, Streamable HTTP at `/mcp` (SSE fallback).

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

Deployment is **manual** (the CD workflow was removed; `.github/workflows/ci.yml`
only runs `ruff format --check` + `ruff check` on pushes/PRs to `main`).

Ship a new revision with the deploy script, which uses a Cloud Run **source
deploy** and reproduces the live config exactly (secrets via Secret Manager,
`REQUIRE_API_KEY=false`):

```bash
bash scripts/deploy.sh
```

Equivalent one-liner:

```bash
gcloud run deploy gammarips-mcp --source=. \
  --project=profitscout-fida8 --region=us-central1 \
  --set-env-vars="REQUIRE_API_KEY=false" \
  --set-secrets="POLYGON_API_KEY=POLYGON_API_KEY:latest,GOOGLE_API_KEY=GOOGLE_API_KEY:latest,GOOGLE_CSE_ID=GOOGLE_CSE_ID:latest"
```

> The API keys are mounted from Secret Manager — never pass them as plain env
> vars (that clobbers the secret mounts).

**Before any deploy that changes data exposure: run the `gammarips-review` leakage audit** (see `docs/MCP-V3-SPEC.md` §2.4).

## Security

See [`SECURITY.md`](./SECURITY.md) for the trust model — read-only guarantee,
parameterized-query SQL-injection defense, response-size bounds, per-IP rate
limits, sanitized errors, leakage-safe views, and the column-classification
data contract.

## License

MIT
