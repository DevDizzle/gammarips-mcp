# Daily Workflow — The Morning Pattern

A reference sequence for an agent working a live trading morning (all times ET).

## Timeline you're operating inside
- **~05:30** — the engine's overnight scan + enrichment lands. The pool for `scan_date = yesterday's session` becomes available.
- **09:30** — market opens.
- **10:00** — the engine's own reference entry anchor (its paper cohort enters here; your agent is free to differ).
- **15:45–16:00** — the engine's same-day reference exit window.

## The sequence

**1. Is today tradeable at all?**
```
get_market_calendar_status()      → open? holiday? early close?
get_regime_context()              → regime_rail_pass?
```
The engine fail-closes on VIX backwardation (spot VIX > VIX3M). Your agent can trade through it — but know you're overriding a rail that exists because short-dated long premium historically bleeds in that regime.

**2. Pull the pool.**
```
get_pool()                        → today's curated candidates + narrative
get_pool(view="preview")          → quick teaser view (free tier)
```
Each row carries the contract the engine's enrichment selected (delta-targeted, short-DTE), flow context (directional dollar volume), technicals, catalyst notes, and a thesis. The pool is BULLISH-only by current policy.

**3. Get quantitative context per candidate.**
```
get_signal(ticker=...)            → full enrichment for one name
query_outcomes(view="summary", horizon="3d", group_by="delta_bucket")
                                  → how similar contracts resolved historically
query_outcomes(view="surface", days=30)
                                  → recent excursion structure of the pool
```

**3.5 Refresh liquidity on your shortlist — the pool's numbers are stale by design.**
```
get_liquidity(contract=recommended_contract, live=True)
                                  → fresh OI, session volume, last trade, day range
```
`recommended_oi`/`recommended_volume` are scan-frozen; the overnight sweep only
becomes visible OI the next morning. This is the decision-time read. (No
bid/ask/spread on the current data plan — the field is absent, not broken.)

**4. Select — your agent's job, not ours.**
Run your own ranking, or the bracket-tournament pattern (`get_playbook("run-your-own-tournament")`). Diversity of selection across subscribers is a feature: the primitives are shared, the conclusions are yours.

**5. Decide the exit BEFORE entry.**
Use `query_outcomes(view="harvest", targets=[...])` for touch probabilities and peak timing, `query_outcomes(view="exit_rule", target_pct=..., stop_pct=...)` to classify your bracket against the surface, and `get_playbook("exit-lab")` for the measured facts (fixed targets tested EV-negative pool-wide; pops land day 2-3; the giveback is large). The single most robust finding in our research: outcomes are decided by exit discipline more than by selection.

**6. After the fact — check receipts, never same-day.**
```
query_outcomes(view="positions", days=30)
                                  → the engine's realized paper trades (T+1)
query_outcomes(view="performance")
                                  → cohort aggregate
```
The engine's own daily selection is intentionally NOT published same-day. Realized rows appear after exit.

## Caveats that bite
- `recommended_oi` / `recommended_volume` are **session-frozen snapshots** from scan time, not live values. Overnight sweeps typically become visible OI only the *next* morning. Re-check with `get_liquidity` before acting on size.
- `recommended_spread_pct` is permanently NULL (no options NBBO on the current data plan). Check spreads with your own broker/data feed.
- Earnings: the pool is NOT earnings-screened. The engine's earnings exclusion runs only at its own cohort's entry, after the pool publishes. Whatever your hold, verify each candidate's earnings date against your horizon with `get_signal(view="earnings")` before acting (IV crush is literature-settled; see [[earnings-exclusion-rail]]).
