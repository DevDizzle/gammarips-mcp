# Changelog — Methodology & Data Changes

Dated record of changes that affect how you should interpret the data. Re-check this playbook periodically; it is the subscription's "what moved" feed.

## 2026-07-02 — MCP V3 surface
- New substrate tools: `get_pool_features`, `get_opportunity_surface`, `query_outcomes`, `get_outcome_summary`, `estimate_exit_rule`, `get_regime_context`, playbooks.
- Same-day pick tools removed (`get_todays_pick`, `list_todays_picks`, `get_open_position`): the engine's own selection is no longer published same-day. Realized receipts remain via `get_position_history` / `get_historical_performance`.
- Live-pool tools now serve a leakage-safe view (forward-outcome columns physically stripped).
- `get_enriched_signal_schema` now returns the full machine-readable column classification (feature/label/opportunity/telemetry/identity + as-of boundaries).

## 2026-06-26 — V7.1 "Tilted GIGO" cohort live
- Live paper-cohort policy: same-day bracket — enter 10:00 ET, +40% target / −30% stop, flat 15:45 ET, no overnight hold. Cohort label `V7_1_TILTED_GIGO`; receipts before this date belong to earlier policies and are not comparable.
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
