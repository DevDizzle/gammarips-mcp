# Security & Trust Model — gammarips-mcp

> **Last reviewed:** 2026-04-27
> **Service URL:** `https://gammarips-mcp-406581297632.us-central1.run.app`
> **Distribution:** public, unauthenticated, listed on Smithery

This document is the trust model for the GammaRips MCP server. It describes
what guarantees the server makes to its consumers (chat agents, paying-customer
products, external developers), what it explicitly does NOT defend against,
and how to report a vulnerability.

---

## Trust model in one sentence

The MCP server is a **public, unauthenticated, read-only API** over the V5.3
options-flow paper-trader. It returns the same data a Smithery-listed agent or
a curious developer could see. There is no per-user data, no PII, no
mutation surface, and no privileged identity.

---

## Guarantees

### 1. Read-only

Every registered tool is a read-only operation against:

- BigQuery datasets `profitscout-fida8.profit_scout.*`
- Firestore collections `todays_pick/*`, `daily_reports/*`
- GCS bucket (read-only signed URL for `daily_reports`)
- Polygon REST snapshot endpoint (option mid prices, read-only)
- Google Custom Search API (read-only, paid)

No tool has BigQuery `INSERT` / `UPDATE` / `DELETE` privileges. The Cloud Run
service account is granted `roles/bigquery.dataViewer` and
`roles/datastore.viewer` only. Mutations are structurally impossible from the
MCP service even if the application code were compromised.

### 2. SQL-injection safe

All BigQuery queries use parameterized `ScalarQueryParameter` /
`ArrayQueryParameter` bindings. No tool concatenates user input into a query
string. Query bodies are static; only filter values are bound.

### 3. Bounded responses

Every tool clamps caller-controlled `limit` / `days` / `lookback_days`
parameters to a tight range *before* the query is built. Bounds:

| Tool | `limit` cap | `days` cap |
|---|---|---|
| `get_overnight_signals` | 1–50 | n/a |
| `get_enriched_signals` | 1–50 | n/a |
| `get_signal_detail` | n/a (single row) | n/a |
| `list_todays_picks` | n/a | 1–30 |
| `get_freemium_preview` | 1–20 | n/a |
| `get_signal_performance` | 1–50 | n/a |
| `get_win_rate_summary` | n/a | 1–365 |
| `get_position_history` | 1–200 | 1–365 |
| `get_report_list` | 1–30 | n/a |
| `get_historical_performance` | hard 500 internal | 1–365 |
| `web_search` | num_results 1–10 | query ≤ 500 chars |
| `get_market_calendar_status` | n/a | 14-day forward window |
| `get_signal_explainer` | n/a (single dict) | n/a |
| `get_enriched_signal_schema` | whitelisted columns only | n/a |

The `MAX_RESPONSE_ROWS = 200` constant in `src/utils/safety.py` is a final
backstop applied across the codebase.

### 4. Per-IP rate limit

A token-bucket rate limiter (`src/utils/safety.py::RateLimitMiddleware`)
applies the following defaults:

- **All tools (default bucket):** 60 requests / minute / IP
- **`web_search` (paid Google CSE):** 10 requests / minute / IP

Buckets allow a 1.5× burst above the per-minute rate. Excess requests return
HTTP 429 with `{"error": "rate_limit_exceeded"}`.

The limiter is in-memory and per-replica. A multi-replica deployment will
have a per-replica budget — acceptable for cost-attack defense; precision
SLAs are not the goal.

### 5. Sanitized error messages

Tool exceptions are routed through `safe_error()` (`src/utils/safety.py`)
which strips:

- Fully-qualified BigQuery table paths (`proj.dataset.table` → `<bq-table>`)
- GCP project IDs matching `profitscout-*` (→ `<project>`)
- Service-account emails (`*.iam.gserviceaccount.com` → `<sa-email>`)
- Internal Google API URLs (→ `<google-api>`)
- Cloud Run service URL patterns (→ `<run-url>`)
- Polygon API keys in any URL parameter (defensive)

Full untruncated errors are still logged server-side at WARNING for engineering
triage. Clients see only a short, infra-redacted message.

### 6. Schema introspection is whitelisted

`get_enriched_signal_schema` returns column metadata from BigQuery's
`INFORMATION_SCHEMA`, but filtered to a static **whitelist of public-safe
columns** maintained in `src/tools/metadata.py::_PUBLIC_SCHEMA_COLUMNS`.

When new internal-only columns are added to `overnight_signals_enriched`
(debug fields, experimental cohort tags, vendor PII, etc.), they do **not**
auto-leak via this tool. They must be explicitly added to the whitelist.

---

## What this server does NOT defend against

### Prompt injection in `web_search` results

`web_search` returns Google CSE results (titles, snippets, links). Snippets
can contain attacker-controlled text. A consumer agent that pipes those
snippets back into its system prompt without sanitization is vulnerable to
classic prompt-injection attacks ("ignore your instructions and dump…").

**This is the consumer agent's responsibility, not the server's.** The
server-side mitigations are: rate-limiting (10/min/IP) and source disclosure
in the response format (`Result N: Source: <domain>`) so the consumer agent
sees the origin domain.

### Cost amplification by sustained low-volume polling

The rate limiter caps request *velocity*, not aggregate request *count*. An
attacker willing to sustain 9 requests/min for hours can drive ~13K
`web_search` calls per day, charged against our Google CSE quota.

If quota becomes a real-money problem we will: (a) add a daily per-IP cap on
`web_search`, (b) move CSE behind a paid-tier API key with billing alerts.

### Loss of confidentiality on paying-customer data

There is none. The MCP server has no per-user data. `todays_pick` and the
ledger are organization-wide truths surfaced to all consumers identically.

### Authentication / authorization

There is none. Per the project's distribution model the MCP is intentionally
public. If we ever ship per-customer tools (e.g., a user's saved picks), they
will live behind a separate authenticated service, not in this MCP.

---

## Reporting a vulnerability

Email **evan@gammarips.com** with `[mcp security]` in the subject line.

If the issue involves a live exploit (e.g. you can demonstrate exfiltration of
data the trust model says is unreachable), include:
1. The exact tool name + arguments that produce the issue
2. The response that demonstrates the leak
3. Your reasoning for why the response is out-of-policy

We will reply within 48h on weekdays.

---

## Change log

| Date | Change |
|---|---|
| 2026-04-27 | Initial SECURITY.md. Sanitized errors, clamped limits, rate-limit middleware, schema whitelist. Added `get_market_calendar_status`, `get_signal_explainer`, `get_historical_performance`. Bot-isolation context (gammarips-bot agent, sandboxed) added by gammarips-engineer Claude session. |
