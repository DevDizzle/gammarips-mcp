# Security & Trust Model — gammarips-mcp

> **Last reviewed:** 2026-07-02 (V3 surface)
> **Service URL:** `https://gammarips-mcp-406581297632.us-central1.run.app`
> **Distribution:** public, unauthenticated (bearer-token tiers are Phase 2 of `docs/MCP-V3-SPEC.md`), listed on Smithery

This document is the trust model for the GammaRips MCP server. It describes
what guarantees the server makes to its consumers (chat agents, paying-customer
products, external developers), what it explicitly does NOT defend against,
and how to report a vulnerability.

---

## Trust model in one sentence

The MCP server is a **public, unauthenticated, read-only API** over the
GammaRips options-flow engine's curated pool and research substrate. It
returns the same data a Smithery-listed agent or a curious developer could
see. There is no per-user data, no PII, no mutation surface, no privileged
identity — and **no same-day pick**: the engine's own daily selection is not
exposed (V3 removed `get_todays_pick` / `list_todays_picks` /
`get_open_position`; only realized T+1 receipts are served).

---

## Guarantees

### 1. Read-only

Every registered tool is a read-only operation against:

- BigQuery datasets `profitscout-fida8.profit_scout.*` (incl. the
  `enriched_option_outcomes` substrate and the leakage-safe views
  `enriched_features_v1` / `overnight_signals_enriched_safe`)
- Firestore collection `daily_reports/*`
- Google Custom Search API (read-only, paid)
- Polygon.io option-snapshot REST API (read-only; `get_contract_snapshot`
  only — constant base URL, contract validated by an anchored fullmatch
  OCC regex before URL placement, API key sent as a bearer HEADER never
  in the URL, 10s timeout, no retries, process-wide 30/min throttle;
  serves NO quote fields)
- Local markdown playbooks vendored in the container (`content/playbooks/`)

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
| `get_freemium_preview` | 1–20 | n/a |
| `get_pool_features` | 1–100 | n/a |
| `get_opportunity_surface` | hard 200 | 1–120 |
| `query_outcomes` | 1–200 | date-range bound |
| `get_outcome_summary` | hard 50 groups | date-range bound |
| `estimate_exit_rule` | aggregate only | target 5–300%, stop 5–95% |
| `get_regime_context` | n/a (single row) | n/a |
| `list_playbooks` / `get_playbook` | local files, name-regex `[a-z0-9-]{1,64}` | n/a |
| `get_signal_performance` | 1–50 | n/a |
| `get_win_rate_summary` | n/a | 1–365 |
| `get_position_history` | 1–200 | 1–365 |
| `get_report_list` | 1–30 | n/a |
| `get_historical_performance` | hard 500 internal | 1–365 |
| `web_search` | num_results 1–10 | query ≤ 500 chars |
| `get_contract_snapshot` | n/a (single contract, strict OCC regex) | 30/min global bucket |
| `get_market_calendar_status` | n/a | 14-day forward window |
| `get_signal_explainer` | n/a (single dict) | n/a |
| `get_enriched_signal_schema` | classification metadata only | n/a |

The `MAX_RESPONSE_ROWS = 200` constant in `src/utils/safety.py` is the
convention every per-tool clamp and hard `LIMIT` is defined against (all row
limits are ≤ 200); it is enforced per-tool, not by a runtime wrapper.

Two guards added after the V3 pre-deploy audit:
- **Pick-flag disclosure guard** — `was_tournament_pick` / `was_topscore_pick`
  are NULLed in every response unless the row's entry day is strictly past
  (ET), so the operator's current selection is structurally unreadable from
  the substrate regardless of when the upstream labeler runs.
- **`web_search` global bucket** — a process-wide token bucket inside the tool
  itself (default 10/min) so the strict search limit holds on ALL transports,
  not just the `/rpc` paths the per-IP middleware can sniff.

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

### 6. Leakage-safe data views (lookahead defense for consumers)

Consumer agents can never see a candidate's future through the pool tools:

- Live-pool tools read `overnight_signals_enriched_safe`, which physically
  strips the forward-outcome columns the win-tracker merges back onto the raw
  enriched table (`next_day_pct`, `day2/3_pct`, `peak_return_3d`, `is_win`,
  `outcome_tier`, ...). Historical dates are safe to query.
- Feature tools read `enriched_features_v1`, an explicit **allowlist** view —
  new/unclassified columns are absent until deliberately classified in, so
  the failure mode is a missing column, never a leaked one.
- Realized data (labels, opportunity surface, receipts) is served only for
  **closed** windows (exit / window-end strictly before today).

`get_enriched_signal_schema` publishes the machine-readable per-column
classification (`feature | label | opportunity | regime_telemetry |
identity` with as-of boundaries) so consumer agents can enforce the same
discipline in their own research. Column descriptions pass through the same
redaction filter as error messages before being surfaced.

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
attacker willing to sustain 9 requests/min for hours can drive many
`web_search` calls per day, charged against our Google CSE quota. Under
**enforce** mode this is largely closed — `web_search` is pro-only, so an
anon attacker can't reach it at all. Until then, mitigations are the per-IP
velocity limit plus the process-wide `web_search` token bucket.

### Loss of confidentiality on paying-customer data

There is none. The MCP server has no per-user data. The pool, substrate, and
ledger receipts are organization-wide truths surfaced to all consumers
identically.

### Authentication / authorization (Phase 2)

Bearer-token auth + tool tiering (`src/utils/auth.py`, `AccessGateMiddleware`):

- **Keys:** `gr_live_<32 hex>`, sent as `Authorization: Bearer <key>` (or
  `X-API-Key`). Resolved by `sha256(key)` → Firestore `mcp_api_keys/{hash}` →
  `{uid, tier, status}`. Plaintext keys are never stored (the doc id is the
  hash). **The MCP only READS this collection** — the webapp owns key issuance
  and Stripe status sync, so the read-only trust model is intact.
- **Tiers:** an `anon` free funnel set (teaser + published-free reports +
  playbooks + pure reference) is usable without a key; everything else
  (`pro` — pool, features, surfaces, outcomes, replay, regime, receipts,
  `web_search`) requires an active key. Tier is on every tool in the server
  card. `web_search` is pro-only (it spends paid CSE quota). The anon set is
  env-overridable (`ANON_TOOLS`).
- **Resolution is fail-closed on privilege, fail-open on availability:** an
  unknown, malformed, revoked, or unverifiable key resolves to `anon` (never
  pro), and a Firestore blip degrades to `anon` rather than 500-ing — a
  transient outage cannot grant privilege, and never caches a failure.
  Positive lookups cache 120s, negatives 60s.
- **Staged rollout (env, no code redeploy to flip):**
  `REQUIRE_API_KEY=true` → **enforce**; `AUTH_SHADOW=true` (with require false)
  → **shadow** (resolves + logs would-be denials, blocks nothing); neither →
  **off**. Deployed in **shadow** first so nothing breaks before the webapp
  issues keys; flip to enforce once keys exist; rollback is an env flip.
- **Denials** return a JSON-RPC error (`code: subscription_required`) with the
  pricing + developers URLs, so a blocked agent can tell its human how to
  upgrade. Discovery (`initialize`, `tools/list`, resources, prompts) is never
  gated — anon agents see the full catalog, pro tools included.
- **Metering:** one structured `MCP_TOOL_CALL` log event per tool call
  (`uid, key_prefix, tool, tier, decision, mode`) → a Cloud Logging sink → BQ
  `mcp_analytics` (one-time GCP setup) does the analytics. No BQ writes from
  the service.

Both single and **batch** JSON-RPC `tools/call` requests are gated — a batched
pro call cannot slip past the gate (every element is evaluated; under enforce
the batch is denied if any element is disallowed). The `/rpc` handler also
re-checks tier against the middleware-resolved identity (defense-in-depth
against a body-sniff/handler parser divergence).

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
| 2026-07-06 | **Eval wave 1+2.** TF-01/03 (bare `win_rate` keys deleted; universe in field names), TF-02 (`get_enriched_signals` summary default + strict `fields` projection + offset paging), TF-15 (`is_tradeable` dropped), TF-04/06/07/09/10/11/12/13/16 polish. **`get_contract_snapshot` added (RM-001a)** — reintroduces a single scoped Polygon snapshot call: bearer-header key, anchored OCC-regex input, 10s timeout, 30/min global bucket, no quote fields (RM-001b blocked on data plan). |
| 2026-07-02 | **Phase 2 auth.** Bearer keys (`gr_live_*` → Firestore `mcp_api_keys/{sha256}`, MCP reads only), anon/pro tool tiering, fail-closed-on-privilege resolution with TTL cache, staged shadow→enforce rollout (env-flagged), structured `subscription_required` denials, `MCP_TOOL_CALL` metering. Deployed in SHADOW. |
| 2026-07-02 | **V3 surface.** Removed same-day pick tools (`get_todays_pick`, `list_todays_picks`, `get_open_position`). Live-pool tools moved to the leakage-safe `overnight_signals_enriched_safe` view (raw table leaked win-tracker forward-outcome columns on historical dates). Added substrate tools (`get_pool_features`, `get_opportunity_surface`, `query_outcomes`, `get_outcome_summary`, `estimate_exit_rule`, `get_regime_context`) and playbooks. Schema tool now serves the column-classification data contract. Streamable HTTP `/mcp` primary transport. Polygon snapshot dependency removed (reintroduced 2026-07-06, scoped — see below). |
| 2026-04-27 | Initial SECURITY.md. Sanitized errors, clamped limits, rate-limit middleware, schema whitelist. Added `get_market_calendar_status`, `get_signal_explainer`, `get_historical_performance`. Bot-isolation context (gammarips-bot agent, sandboxed) added by gammarips-engineer Claude session. |
