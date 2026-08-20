Status: active
Type: methodology
Tag: policy-adopted
Exit-context: n/a (a pool-admission definition, not a measured edge)
Source: GammaRips methodology
Date: 2026-08-20

# "Enriched" = overnight_score >= 1 + directional UOA > $500K

The curated pool has exactly two admission criteria at the scan stage:
- **`overnight_score >= 1`** — a cosmetic floor. The UOA bar, the BULLISH-only gate, and
  the top-50 cap do the real filtering. History: earlier docs claimed a `>= 4` floor, but
  that floor never ran in production, and the owner accepted the `>= 1` floor on
  2026-08-20. The old evidence stays valid as history: EV inverts at `>= 7`, so a HIGHER
  threshold is worse, not better.
- **directional unusual-options-activity (UOA) > $500K**.

At this cheap scan/UOA stage the pool is **all directions**. The BULLISH-only narrowing
([[bullish-only-hard-gate]]) and the top-N edge-rank cap ([[tourney-pool-cap-edge-rank]])
happen downstream, before the selection tournament. Spread is NOT an admission criterion —
it is permanently retired ([[spread-gate-retired]]).

Application: `get_pool(view="enriched")` returns exactly this admitted set (~50 BULLISH
names/day). The wider pre-curation scan is a separate surface (`get_pool(view="raw")`).
