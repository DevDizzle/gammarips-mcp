# MCP V3 — Reimagined Tool Surface + Paid-Access Governance

> **Status:** SPEC — approved-pending-owner-review (drafted 2026-07-02)
> **Supersedes:** `PROMPT-MCP-V2-OVERHAUL.md` (the free/no-auth V2 overhaul, executed ~Q1) and `docs/MCP_AUTH.md` (auth design referencing an `src/auth/` module that no longer exists in the tree).
> **Positioning source of truth:** `gammarips-engine/NEXT_SESSION_PROMPT.md` (owner-locked 2026-07-02) — free human UI, monetize ONLY MCP access; sell data + tools as a data vendor, never a pick, never a return.

---

## 0. Why V3

The current server (18 tools, rev `00027-mcl`-era code) was built for the old free-funnel product and has drifted from both the live trading policy and the new business model:

| Problem | Evidence |
|---|---|
| **Pick leak** — the operator's now-private daily signal is exposed unauthenticated, and even advertised as `primary_tool` in `mcp.json` / the server card | `get_todays_pick`, `list_todays_picks`, `get_open_position` |
| **Leakage into agents** — `get_enriched_signals` / `get_signal_detail` do `SELECT *` on raw `overnight_signals_enriched`, which carries win-tracker forward-outcome columns (`next_day_pct`, `day2_pct`, `day3_pct`, `peak_return_3d`, `is_win`, `outcome_tier`, …). Any historical query hands an agent the future. | `src/tools/overnight_signals.py` |
| **Policy drift** — descriptions still describe V6 (−60/+80, 3-day hold). Live policy is V7.1 Tilted GIGO (10:00 entry, +40/−30, flat 15:45, same-day). | tool descriptions throughout |
| **The actual product isn't exposed** — the leakage-safe research substrate (`enriched_features_v1`, `enriched_option_outcomes`, the `opp_*` opportunity surface, `mom_60`, regime features) is what we sell, and zero tools serve it. | engine substrate audit 2026-07-01/02 |
| **No auth** — `REQUIRE_API_KEY=false` posture, deliberately; the paid pivot needs per-subscriber tokens, tiers, metering. | `scripts/deploy.sh`, `SECURITY.md` |
| **Legacy transport** — SSE-first with a hand-rolled stateless `/rpc`; protocol pinned to `2024-11-05`. Streamable HTTP is the current standard. | `src/server.py` |

**Phasing (owner-directed):**
- **Phase 1** — modernize the server and ship the full read-only decision-support tool surface (no auth change; anonymous during build-out).
- **Phase 2** — token auth for paid subscribers + tiering + rate limits + metering.
- **Phase 3** — webapp integration (key issuance UI, Stripe sync, /developers rewrite) — implemented in `gammarips-webapp` by the owner; this spec defines only the contract.

---

## 1. Non-negotiable invariants (all phases)

1. **Primitives, not picks.** No tool may return "the trade to make." The tournament is exposed as a documented *pattern* the user's agent runs itself. The operator's daily pick never appears same-day on any tool.
2. **Sell the opportunity surface, not a return.** The whole-pool GIGO composite is negative (≈ −2 to −6%/day); no tool may present a whole-pool composite as a tradeable ROI. The honest product is per-contract realized excursions (`opp_*`) + labels + features, with exit as the user's free variable.
3. **Leakage-safety is physics.** Features are served ONLY through the allowlist views (`enriched_features_v1`, `overnight_signals_enriched_safe`); the raw `enriched_option_outcomes` table is touched only for label/opportunity columns joined back to view-served features. Realized data is served only for **closed** windows (exit/window-end strictly < today ET).
4. **Every tool** uses `safe_error`, `clamp`, parameterized queries, and explicit column selection or view-mediated `SELECT *`. `MAX_RESPONSE_ROWS` backstop stays.
5. **Read-only trust model stays intact in Phases 1–2.** SA remains `bigquery.dataViewer` + `datastore.viewer`; usage metering goes through Cloud Logging (log sink → BQ), never direct BQ writes from the service.
6. **Data-not-advice framing** in the server card, README, and every performance-adjacent tool description ("Paper-traded. Educational data. Not investment advice.").
7. **`gammarips-review` audit before deploying any data-exposure change** (this whole spec qualifies).

---

## 2. Phase 1 — Modernization + the decision-support surface

### 2.1 Transport & protocol

- Add **Streamable HTTP** as the primary transport at `/mcp` (FastMCP ≥2.6 `http_app()`); advertise it first everywhere.
- Keep `/sse` for a deprecation window (existing consumers incl. the sandboxed bot); keep stateless `/rpc` + `/jsonrpc` (Smithery) and the server card.
- Bump advertised protocol version off the hardcoded `2024-11-05`; let the SDK negotiate on `/mcp`, and update the stateless handler to a current version string.
- Server card / `mcp.json` / README: remove `primary_tool: get_todays_pick`; re-describe the server in data-vendor terms ("curated overnight options pool + realized opportunity surfaces + methodology primitives — your agent decides").

### 2.2 Tool surface (23 tools)

#### KEEP as-is (8) — description de-drift only where noted
| Tool | Note |
|---|---|
| `get_overnight_signals` | raw scanner rows; already column-explicit |
| `get_freemium_preview` | stays the anonymous teaser |
| `get_daily_report`, `get_report_list` | free content (published on the website anyway) |
| `get_available_dates` | |
| `get_market_calendar_status` | |
| `get_signal_explainer` | EXTEND: add entries for `mom_60`, `opp_peak_return`, `opp_trough_return`, `realized_return_pct` (GIGO semantics), `vix_at_scan`, `label_*` tags, session-frozen OI/volume caveat |
| `web_search` | unchanged (rate-limit posture revisited in Phase 2) |

#### REWRITE (7)
| Tool | Change |
|---|---|
| `get_enriched_signals` | **Read `overnight_signals_enriched_safe`** (kills the forward-outcome leak). De-drift docstring to V7.1. Keep name/params (existing consumers). |
| `get_signal_detail` | Same safe-view switch. |
| `get_signal_performance` | Keep, but description must lead with: **underlying-stock direction outcomes, NOT option PnL** (underlying-up 54% vs option-up 41% on the same pool). Response gains `"universe": "underlying_direction"` marker. |
| `get_win_rate_summary` | Same disambiguation; rename response fields to `underlying_direction_win_rate` etc. |
| `get_position_history` | De-drift to V7.1 GIGO mechanics; add `policy_version` filter (default `V7_1_TILTED_GIGO`); keep the realized-only guard (`exit_timestamp < today ET`), keep skip rows visible. This becomes the **delayed receipts** tool. |
| `get_historical_performance` | Cohort-aware: default to the live `V7_1_TILTED_GIGO` cohort (`LIVE_COHORT_START_DATE=2026-06-26`), explicit `policy_version` param; never mix cohorts in one aggregate. |
| `get_enriched_signal_schema` | Serve the **machine-readable column classification** from `INFORMATION_SCHEMA` column descriptions (the 97-tag `feature | label | opportunity | regime_telemetry | identity` vocabulary + as-of boundaries), so agents can physically refuse non-feature inputs. |

#### REMOVE (3)
`get_todays_pick`, `list_todays_picks`, `get_open_position` — same-day exposure of the private signal.
Receipts continuity: realized picks (ticker, contract, entry/exit, return, skip days) remain fully visible T+1 via `get_position_history` / `get_historical_performance`.
> **Owner decision:** hard removal (recommended) vs. a `PICK_DISCLOSURE_DELAY_DAYS`-gated variant. Removal is cleaner: a delayed pick is just a receipts row, which we already serve.

#### NEW (8) — the substrate tools
All read paths per invariant #3. All date params `YYYY-MM-DD`; all limits clamped.

1. **`get_pool_features(scan_date?, ticker?, limit=50)`**
   Point-in-time feature vectors for the curated pool. Source: **`enriched_features_v1`** (35 cols today; `mom_60` + scan-date regime cols appear automatically once engine Phase C activates them in the view — see §2.5). This is the quantitative companion to `get_enriched_signals` (which serves the narrative enrichment).

2. **`get_opportunity_surface(scan_date?, ticker?, days=30, include_open=false)`**
   Per-contract realized MFE/MAE excursions: `opp_peak_return`, `opp_trough_return`, `opp_minutes_to_peak/trough`, `opp_entry_price`, `opp_window_days`, `opp_status`, `opp_sim_version` + identity/contract columns. Source: `enriched_option_outcomes`, `opp_status='OK'` by default (closed windows only). The flagship product tool.

3. **`query_outcomes(horizon='same_day'|'3d', scan_date_from?, scan_date_to?, ticker?, delta_min?, delta_max?, min_overnight_score?, exit_reason?, limit=100)`**
   Row-level realized labels joined to view-served features: label columns for the requested horizon (`realized_return_pct` + `exit_reason` + fill realism, or the `*_3d` group) + `label_*` semantics tags + the feature vector from `enriched_features_v1`. Excludes `illiquid_exit=TRUE` and NULL labels by default (exclusions reported in response meta — the ~27.7% `INVALID_LIQUIDITY` tail is non-random and must be disclosed, not hidden). Horizons are never pooled.

4. **`get_outcome_summary(horizon, group_by='none'|'delta_bucket'|'overnight_score'|'premium_score'|'exit_reason'|'day_of_week', scan_date_from?, scan_date_to?)`**
   Aggregates over the labeled pool: `n`, `win_rate`, `avg/median return`, `p25/p75`, `avg MFE`, `avg MAE`, excluded-row counts. `group_by` is a strict whitelist (no free-form dimensions). (`mom_60` bucket joins the whitelist post-Phase C.) Response carries a fixed disclaimer: whole-pool composites under fixed exits are negative; this is a research surface, not a strategy return.

5. **`estimate_exit_rule(target_pct, stop_pct, horizon='3d', scan_date_from?, scan_date_to?)`**
   "Bring your exit, we score it." Classifies each closed-window contract against the user's bracket using MFE/MAE: definitive TARGET (peak ≥ target, trough never ≤ stop), definitive STOP (inverse), and TIMEOUT (neither crossed — return bounded by [MAE, MFE], window-end price not stored). **Owner decision 2026-07-02: no AMBIGUOUS bucket** — rows where BOTH levels crossed are resolved by extreme order (minutes-to-peak vs minutes-to-trough) and tagged `TARGET_HEURISTIC`/`STOP_HEURISTIC`, with `heuristic_share` reported so results can be bounded with/without them. Returns bucket counts, `est_win_rate` (+ definitive-only variant), EV bounds, plus exact realized stats when `(target,stop,horizon)` matches a labeled rule (+40/−30 same-day; +80/−60 3-day). Params clamped (target 5–300%, stop magnitude 5–95%). **Exact first-crossing replay requires the minute-path companion table (engine must-fix #6g, deferred) — the honesty contract stands: heuristic resolutions are always tagged, never presented as exact.**

6. **`get_regime_context(scan_date?)`**
   Scan-date regime features: `vix_at_scan`, `vix3m_at_enrich`, `spy_trend_at_scan`, `vix_5d_delta_at_scan` + computed `regime_rail_pass = (vix <= vix3m)` + the rail's plain-English definition. Served from the substrate's per-day constants (no standalone `market_regime_daily` table exists yet — engine SHOULD-FIX; adopt it here when built). Only exists for days with a pool; says so when absent.

7. **`list_playbooks()`** and 8. **`get_playbook(name)`**
   Server-versioned methodology markdown from `content/playbooks/` in this repo, also registered as MCP **resources**. Initial set:
   - `start-here` — what this server is, what it deliberately is not (no picks), how the pieces compose
   - `daily-workflow` — the morning pattern: calendar → regime → pool → features → surfaces → your agent's own selection
   - `run-your-own-tournament` — the randomized-bracket selection pattern as a BYO-agent recipe (batches ≤10, top-2 advance, 3-bracket consensus), explicitly parameterized by the *user's* criteria
   - `exit-lab` — how to use `get_opportunity_surface` + `estimate_exit_rule` + `query_outcomes` to explore the exit space; why fixed-exit composites mislead
   - `leakage-and-data-contract` — the feature/label/telemetry vocabulary, as-of boundaries, session-frozen fields (OI/volume/spread caveats)
   - `changelog` — dated methodology/data changes (subscription = living research)
   Content is condensed from engine docs and sanitized (no internal table paths beyond the whitelisted schema tool, no service URLs).

#### MCP prompts (replace the 3 existing)
`morning_brief(direction?)`, `analyze_candidate(ticker)`, `run_your_own_tournament()` — each a thin orchestration over the tools + playbooks above. No prompt references a pick.

### 2.3 Data caveats every relevant tool must carry (descriptions/response meta)
- `recommended_oi` / `recommended_volume` / `volume_oi_ratio` / `moneyness_pct` — **session-frozen snapshots**, not point-in-time.
- `recommended_spread_pct` — permanently NULL on this data plan; pre-2026-06-04 values unreliable.
- `signal_performance` universe = underlying direction, never option PnL.
- Same-day vs 3-day labels are distinct horizons; never pooled.

### 2.4 Testing & rollout (Phase 1)
1. Extend `tests/` (`verify_tools.py`, `test_scenarios.json`) to the new surface; every tool needs a live-data assertion + a leakage assertion (no forward-outcome / `oc_*` / label column in any feature-tool response; no row with open window from surface/outcome tools).
2. **`gammarips-review` audit (mandatory)** — lookahead/leakage pass over every new query path.
3. Deploy via `scripts/deploy.sh` (posture unchanged: `REQUIRE_API_KEY=false` in Phase 1).
4. Live end-to-end verification of all 23 tools; update `README.md`, `SECURITY.md`, `mcp.json`, server card.

### 2.5 External dependencies on `gammarips-engine`
| Dependency | Status | Impact if missing |
|---|---|---|
| **Phase C view activation** (`mom_60`, `mom_anchor/lookback`, `vix_at_scan`, `spy_trend_at_scan`, `vix_5d_delta_at_scan` uncommented into `enriched_features_v1`) | pending | `get_pool_features` serves 35 cols without the flagship lever; tools are written against the view so they pick the columns up automatically |
| Minute-path companion table (must-fix #6g) | deferred | `estimate_exit_rule` stays bounds-only (by design) |
| `market_regime_daily` table | should-fix, not built | `get_regime_context` serves from substrate per-day constants |

---

## 3. Phase 2 — Auth, tiers, governance

### 3.1 Key model
- Format: `gr_live_` + 32 hex chars (16 random bytes). Shown once at generation.
- Storage: Firestore **`mcp_api_keys/{sha256(key)}`** → `{ uid, tier: "pro", status: "active"|"revoked", created_at, label? }`.
  - Doc-ID-by-hash → single `get()` lookup, no index, plaintext never stored.
  - **The MCP server only reads this collection.** The webapp (Phase 3) owns writes: create on generation, `status:"revoked"` on rotation or subscription lapse (Stripe webhook). This keeps the MCP decoupled from the webapp's `users` schema (supersedes `MCP_AUTH.md` Option A).
- Firestore rules: `mcp_api_keys` is admin-SDK-only (no client read/write); key generation happens in a webapp server action, not the client SDK.

### 3.2 Enforcement
- `AuthMiddleware` (ahead of the rate limiter, all transports incl. `/mcp`, `/sse`, `/rpc`): extract `Authorization: Bearer …` (accept `X-API-Key` alias) → SHA-256 → Firestore lookup with in-process TTL cache (300s positive / 60s negative) → attach `user_info = {uid, tier}` (or `tier: "anon"`).
- Per-tool gating in `execute_tool` + a FastMCP wrapper via a single `TOOL_TIERS` map:
  - **`anon` (free):** `get_freemium_preview`, `get_market_calendar_status`, `get_signal_explainer`, `get_available_dates`, `get_daily_report`, `get_report_list`, `list_playbooks`, `get_playbook("start-here")`.
  - **`pro` (paid key):** everything else — pool, features, surfaces, outcomes, replay, regime, full playbooks, receipts, `web_search`.
- Denials return a structured, friendly error (`code: subscription_required`, docs + pricing URL) — an agent hitting the wall should be able to tell its human exactly how to upgrade.
- `REQUIRE_API_KEY` staged rollout: `false` → **shadow mode** (`AUTH_SHADOW=true`: log would-be denials, block nothing) → `true`. Rollback = flip env var.

### 3.3 Rate limits & cost control
- Anonymous: per-IP bucket, tightened (30/min default); `web_search` becomes **pro-only** (it spends paid CSE quota).
- Pro: per-key bucket (120/min default; env-tunable), separate `web_search` bucket (20/min). Flat monthly + generous limits — no per-call metering pricing (usage anxiety churns subscribers).

### 3.4 Metering & analytics (read-only trust model preserved)
- Structured log event per tool call: `MCP_TOOL_CALL {uid, key_prefix, tool, status, duration_ms, row_count, tier}`.
- Cloud Logging **sink → BQ dataset `mcp_analytics`** (one-time GCP setup) for usage dashboards, abuse detection, and churn signals (per-uid daily-active-tool trends). No direct BQ writes from the service; SA stays viewer-only.
- `SECURITY.md` trust-model update ships in the same PR as the auth flip.

### 3.5 Client-compat note
Bearer-header auth works today in Claude Code (`--header`), Cursor, OpenClaw, and the SDKs. claude.ai web custom connectors prefer OAuth — **OAuth 2.1 (dynamic client registration) is Phase 2b**, additive, after bearer keys prove out.

---

## 4. Phase 3 — Webapp contract (implemented in `gammarips-webapp`)

The MCP side requires exactly this from the webapp:
1. **Key lifecycle:** `/account` section — generate (show-once), rotate (revoke + new), revoke. Server action writes `mcp_api_keys/{hash}` and mirrors non-secret metadata (`createdAt`, `keyPrefix`) on `users/{uid}` for display.
2. **Subscription sync:** Stripe webhook flips `status` on lapse/renewal.
3. **`/developers` rewrite:** endpoint (`/mcp` first), auth quickstarts (Claude Code, Cursor, OpenClaw, raw SDK), the 23-tool catalog, data-vendor/not-advice framing, pricing link.
4. Firestore rules per §3.1.

---

## 5. Deferred / later (explicitly out of scope for Phases 1–2)
- **Skills repo + Claude Code plugin + MCP Registry listing** — free distribution wrappers once the surface stabilizes (skills mirror the playbooks; plugin bundles `.mcp.json` + skills + an analyst agent).
- **Decision journal** (`log_decision` / `get_my_track_record`) — the strongest retention lever, but it's a write surface → trust-model + IAM change; design doc after Phase 2. Get securities-counsel review alongside (closest tool yet to the advice line).
- **Exact exit replay** — unlocked by the engine minute-path table.
- **MCP Apps widgets** (inline pool/surface charts) — polish.
- **OAuth 2.1** — Phase 2b.

## 6. Owner decisions
1. ~~Pick tools: hard removal vs delayed variant~~ — **RESOLVED 2026-07-02: hard removal, implemented in Phase 1.**
2. ~~estimate_exit_rule ambiguity~~ — **RESOLVED 2026-07-02: no AMBIGUOUS bucket; heuristic resolution + tagging (§2.2 item 5).**
3. `web_search`: pro-only (recommended) vs tightened anon — decide in Phase 2.
4. Anonymous access to `get_overnight_signals` (raw scan feeds the free SEO pages — recommend **keep anon**, it's already public on the site) — decide in Phase 2.
5. Pricing/tier naming — out of scope here; single `pro` tier assumed.

## 7. Phase 1 implementation status (2026-07-02)
Landed on branch `mcp-v3-phase1`: all 23 tools, 3 prompts, playbook resources, Streamable HTTP `/mcp` primary + legacy `/sse` + stateless `/rpc`, registry-generated tool list (single source of truth = docstrings), 6 playbooks in `content/playbooks/`, smoke suite `tests/test_v3_smoke.py` (27/27 incl. leakage + negative tests), README/SECURITY/mcp.json updated. Verified end-to-end over the real MCP protocol against live BigQuery.
