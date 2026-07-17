Status: active
Type: methodology
Tag: policy-adopted
Exit-context: the soft pre-rank levers come from the 1,375-trade 3-day-bracket study
Source: GammaRips methodology
Date: 2026-07-17

# The pool is soft-edge-ranked, then capped, before the tournament

Among the BULLISH names, the pool is **deterministically edge-ranked and capped** to a
top-N set before the selection tournament — a cost control (the full ~94-name tournament
was far more model calls per pick than a capped one).

The rank is a **SOFT pre-rank** (a tilt, not a gate) by the 1,375-trade study's levers:
mid-|delta| 0.20-0.46 ([[delta-band-0-20-0-46]]), reward/risk < 1.4, and ATR-normalized
move — all point-in-time / leakage-safe ([[leakage-safety-gate]]). The fallback path keeps
the [[bullish-only-hard-gate]] but skips the edge-cap.

The effective cap is ~50 and rarely binds, because enrichment already narrows to ~50
BULLISH names upstream. A ceiling study shows the cap can shrink 50->25 with no demonstrated
loss of the eventual winner (best-name capture: N=25 -> 93.5%, N=10 -> 56%), roughly halving
selection-model cost — a ceiling test (does the winner survive the cap), not a test of pick
quality inside the pool.
