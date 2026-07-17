# GammaRips MCP Server

[![smithery badge](https://smithery.ai/badge/gammarips/Options-Intelligence)](https://smithery.ai/servers/gammarips/Options-Intelligence)

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

## Available tools (9)

V4 (2026-07-17) consolidated the 29-tool V3 surface into 9. The absorbed tools
live on as `view=` / `granularity=` modes of these 9. `web_search` was removed.

**Free tier** (no key): `get_pool`, `get_regime_context`,
`get_market_calendar_status`, `get_playbook`, `get_daily_report`.
**Pro tier** (Agent Access, $39/mo key): `get_signal`, `get_liquidity`,
`query_outcomes`, `replay_contract`.

- `get_pool` **(free)** — the candidate pool: `view="enriched"` (curated
  narrative/technicals/contract/`mom_60`, leakage-safe view; default),
  `"raw"` (pre-curation scan), `"features"` (point-in-time feature vectors
  from the allowlist view), `"preview"` (public teaser).
- `get_signal` **(pro)** — one ticker: `view="detail"` (full enrichment,
  default) or `view="earnings"` (the doctrine earnings-window check).
- `get_liquidity` **(pro)** — fresh entry-day liquidity: a single `contract`
  (cache-first, `live=true` to force upstream) or the whole pool / a
  `contracts` shortlist in one call. No quote fields on this data plan.
- `query_outcomes` **(pro)** — the outcomes + receipts substrate, via `view=`:
  `labels` (row-level bracket labels + features; default), `summary` (grouped
  aggregates), `surface` (per-contract MFE/MAE excursions, exit-free),
  `harvest` (touch-probability curve), `exit_rule` (score YOUR bracket/trailing
  rule), `signal_performance` / `win_rate` (UNDERLYING-direction, **not** option
  PnL), `positions` / `performance` (the engine's realized paper-trade receipts,
  cohort-filtered, default live `V7_1_TILTED_GIGO`).
- `replay_contract` **(pro)** — raw price tape for your own exit rule:
  `granularity="minute"` (intraday path + exact first-crossing; default) or
  `"day"` (daily OHLCV mark series). This server does not simulate exits.
- `get_regime_context` **(free)** — VIX/VIX3M/SPY-trend as-of scan date + the
  fail-closed regime rail.
- `get_market_calendar_status` **(free)** — `view="status"` (NYSE open/close,
  default) or `view="scan_dates"` (which scan dates have data).
- `get_playbook` **(free)** — methodology + reference: no arg lists the
  catalog; `name=` fetches a playbook (`start-here`, `daily-workflow`,
  `run-your-own-tournament`, `exit-lab`, `leakage-and-data-contract`,
  `changelog`) or `name="schema"` the machine-readable data contract (per-column
  leakage classification); `field=` explains any signal field (deterministic,
  no LLM). Playbooks are also MCP resources (`gammarips://playbooks/{name}`).
- `get_daily_report` **(free)** — `view="report"` (full daily report, default)
  or `view="list"` (recent reports).

### Removed
`web_search` (V4). The engine's own daily selection is not published same-day
(`get_todays_pick` / `list_todays_picks` / `get_open_position` removed in V3);
realized receipts remain via `query_outcomes(view="positions")`.

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

Omit `headers` for the free tier (5 anon tools).

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

Free tier works with no account: `get_pool`, `get_regime_context`, `get_market_calendar_status`, `get_playbook`, `get_daily_report`. Pro tools (`get_signal`, `get_liquidity`, `query_outcomes`, `replay_contract`) require Agent Access ($39/mo) — generate a key at [gammarips.com](https://gammarips.com/pricing).

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
