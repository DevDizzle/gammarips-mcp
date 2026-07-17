Status: active
Type: methodology
Tag: policy-adopted
Exit-context: n/a (a pool-admission definition, not a measured edge)
Source: GammaRips methodology
Date: 2026-07-17

# "Enriched" = overnight_score >= 4 + directional UOA > $500K

The curated pool has exactly two admission criteria at the scan stage:
- **`overnight_score >= 4`** — a FLOOR, not a ceiling. EV inverts at `>= 7`, so a higher
  threshold is worse, not better; the floor holds at 4.
- **directional unusual-options-activity (UOA) > $500K**.

At this cheap scan/UOA stage the pool is **all directions**. The BULLISH-only narrowing
([[bullish-only-hard-gate]]) and the top-N edge-rank cap ([[tourney-pool-cap-edge-rank]])
happen downstream, before the selection tournament. Spread is NOT an admission criterion —
it is permanently retired ([[spread-gate-retired]]).

Application: `get_pool(view="enriched")` returns exactly this admitted set (~50 BULLISH
names/day). The wider pre-curation scan is a separate surface (`get_pool(view="raw")`).
