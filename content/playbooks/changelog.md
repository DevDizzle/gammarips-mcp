# Changelog — Methodology & Data Changes

Dated record of changes that affect how you should interpret the data. Re-check this playbook periodically; it is the subscription's "what moved" feed.

## 2026-08-10 — Live cohort RESET to 2026-08-10; receipts restart at zero (applied 2026-08-07)
- **The receipts views return `total_trades: 0` / `row_count: 0` until the new cohort accrues closed trades.** That is a cohort reset, not missing data and not a zero win rate. Aggregate stats (`win_rate`, `avg_return`, `best`, `worst`) come back `null` at N=0 — deliberately NOT `0.0`, because an invented zero is worse than an absent number.
- **The cohort is a PAIR, not a label.** It is `policy_version='V7_1_TILTED_GIGO'` **AND** entry on/after `2026-08-10`. Responses now carry a `cohort_start` field. The ledger keeps earlier cohorts under the same policy label, because resets since 2026-07-28 are date-filter resets rather than truncations — so filtering on the label alone silently mixes in disowned rows.
- **Why the reset:** the engine found that the early-print liquidity floor introduced on 2026-07-29 had never actually fired. The options data vendor never returns a zero-volume day bar for a contract that has not traded today; it returns the PRIOR session's bar, so "yesterday's total volume" was read as "prints so far this morning". Two picks in the 2026-07-29 cohort were selected on a phantom liquidity count. The engine fixed the read, disowned that cohort, and restarted.
- **`policy_version="all"` now warns you.** It still reaches every era, but those rows include cohorts the engine has repudiated. Do not aggregate them into a single track record.
- Realized-only still applies: a trade appears the day AFTER it exits, so these views read one session behind the engine's own public panel.

## 2026-07-29 — Cohort reset: tournament liquidity upgrade — SUPERSEDED
- Cohort restarted at entry 2026-07-29 for a two-tier print / open-interest slate floor and a liquidity-aware judge prompt. **Superseded 2026-08-10 (see above):** that cohort's primary floor never fired, and the cohort is disowned.

## 2026-07-17 — v4: 9-tool consolidation + methodology corpus
- The surface consolidated from ~29 tools to **9**. Older tool names are now `view=`/`granularity=` modes on the 9:
  - pool reads → `get_pool(view="enriched"|"raw"|"features"|"preview")` — `preview` is free; `enriched`/`raw`/`features` need an active key.
  - one ticker → `get_signal(view="detail"|"earnings")`; fresh entry-day liquidity → `get_liquidity`.
  - all outcomes + receipts → `query_outcomes(view=...)`: `positions` (was get_position_history), `performance` (was get_historical_performance), `surface` (was get_opportunity_surface), `harvest` (was get_harvest_curve), `exit_rule` (was estimate_exit_rule), `signal_performance`, `win_rate`, `summary`, `labels`.
  - price tape → `replay_contract(granularity="minute"|"day")`; calendar → `get_market_calendar_status`; methodology → `get_playbook`; regime → `get_regime_context`; report → `get_daily_report`.
  - `web_search` removed.
- NEW methodology corpus behind `get_playbook` (free): start at `get_playbook("methodology")` for the selection logic (how the pool is built and why), the edge findings, and the supporting literature.

## 2026-07-06 — Research drop + tool wave (the living-research feed, working)
**Three pre-registered studies (two on all expired pool contracts, Apr 10 - Jun 30 2026 scans; one on all closed 3-day excursion windows, scans through Jun 26):**
- **Delta-calibrated:** realized ITM-at-expiry 41.3% vs mean scan-time |delta| 42.1% (N=2,146) — the pool converts at the market-implied rate; treat |delta| as your base rate.
- **IV-calibrated path:** realized excursion peaks at the ~51st percentile of each contract's own entry-IV-implied distribution (N=1,303) — big peaks, exactly as priced.
- **Harvest curve + timing + giveback (N=2,029):** P(touch +20% in the 3-day window) = 51%, +100% = 14%; peaks ≥ +20% land day 3 ~52% of the time (day 1 only ~15%); every fixed target ≤ +80% tested EV-negative pool-wide; conditional on touching +50%, the median contract kept only 31% of its peak at expiry and ~48% of ever-profitable contracts expired at a loss.
Full context in `get_playbook("exit-lab")`. One regime arc so far — these re-run as eras accrue.

**Tool changes (same day):**
- NEW `get_contract_snapshot` — fresh entry-day OI / session volume / last trade / day range per contract (scan-frozen pool numbers finally have a live companion). No bid/ask/spread on the current data plan — deliberately absent, not NULL.
- NEW `get_harvest_curve` — the touch-probability curve with CIs, day-of-peak buckets, and stop-touch rates, computed live with your filters.
- `get_win_rate_summary` / `get_signal_performance`: the bare `win_rate` key is GONE — the headline is `underlying_direction_win_rate` (it was never option PnL; now the field name says so).
- `get_enriched_signals`: compact summary default (full pool fits in one response), strict `fields` projection, `offset` paging. `is_tradeable` removed everywhere (it was a legacy premium-flag combo, not a liquidity verdict).
- `estimate_exit_rule` labeled research-only; `get_signal_detail` trims long narrative by default (`full=true` restores) and now tells you when a ticker simply isn't in the pool; lag notes on `get_pool_features`/`get_regime_context`; `moneyness_bucket` grouping; `aggregate_only` mode on `query_outcomes`.

## 2026-07-02 — MCP V3 surface
- New substrate tools: `get_pool_features`, `get_opportunity_surface`, `query_outcomes`, `get_outcome_summary`, `estimate_exit_rule`, `get_regime_context`, playbooks.
- Same-day pick tools removed (`get_todays_pick`, `list_todays_picks`, `get_open_position`): the engine's own selection is no longer published same-day. Realized receipts remain via `get_position_history` / `get_historical_performance`.
- Live-pool tools now serve a leakage-safe view (forward-outcome columns physically stripped).
- `get_enriched_signal_schema` now returns the full machine-readable column classification (feature/label/opportunity/telemetry/identity + as-of boundaries).

## 2026-06-26 — V7.1 "Tilted GIGO" cohort live — SUPERSEDED
- Live paper-cohort policy: same-day bracket — enter 10:00 ET, +40% target / −30% stop, flat 15:45 ET, no overnight hold. The **exit mechanics above are still current**; only the cohort boundary moved. **Superseded as a cohort start twice — 2026-07-29, then 2026-08-10 (current).** Receipts before 2026-08-10 belong to disowned or earlier cohorts and are not the live track record.
- Selection unchanged (randomized bracket tournament over the BULLISH pool) plus a 60-day-momentum pre-rank tilt.

## 2026-06-25 — Live open-interest floor at selection
- The engine re-checks LIVE open interest on the morning of entry and drops contracts below a floor before its own selection. Substrate OI columns remain scan-time snapshots — this live check is deliberately not backfilled into historical data.

## 2026-06-17 — Same-day GIGO exit (V7)
- Reference exit moved from a 3-day −60/+80 bracket to the same-day +40/−30 bracket. The 3-day bracket lives on as the `3d` label horizon for research.

## 2026-06 — Opportunity surface + momentum features
- Exit-free MFE/MAE excursion surface (`opp_*`) computed for the full pool over a 3-trading-day window, backfilled to ~April 2026.
- `mom_60` (60-day underlying momentum, point-in-time-guarded) added to the pool features. Historically the strongest conditional lever *under the 3-day horizon* in combination with mid-|delta| 0.20–0.46; shows no edge under the same-day bracket. Treat as a research lead, not a rule.

## 2026-06-05 — Spread data retired
- The data plan serves no options NBBO; `recommended_spread_pct` is permanently NULL and pre-June values are unreliable.

## 2026-06-04 — Selection gates removed upstream
- Legacy moneyness / V-OI / volume / DTE gates retired (they filtered on stale scan-time snapshots and removed real winners). The pool you see is gated only by enrichment score + directional flow, an earnings exclusion, and the VIX≤VIX3M regime rail.
