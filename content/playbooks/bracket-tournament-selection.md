Status: active
Type: methodology
Tag: policy-adopted
Exit-context: n/a (the selection layer; the exit is [[gigo-same-day-exit]])
Source: GammaRips methodology
Date: 2026-07-17

# Selection is a randomized bracket tournament — one signal/day or none

The engine selects with a **randomized bracket tournament** over the curated pool. It
produces **one signal per day or none**.

Mechanics: **3 independent brackets**, each shuffles the capped pool into batches of <=10,
**top-2 advance** per batch, repeated down to a single winner. The **consensus** winner
across the 3 brackets is the selection, and agreement sets confidence: **3/3 = high,
2/3 = medium, 1/3 = low**. The prompt is dead-simple ("buy a single option, sell it for a
profit") plus the daily report for context plus per-contract data — **no memory, no rubric,
no weights**. It is **fail-closed on error: no fallback** (an error produces no selection,
never a degraded one).

Inputs: the enriched pool after the [[bullish-only-hard-gate]] and the
[[tourney-pool-cap-edge-rank]] soft pre-rank, past the two safety rails
([[earnings-exclusion-rail]], [[regime-rail-vix-term]]), each [[leakage-safety-gate]]-checked.

This is a *pattern*, not a pick endpoint — you run it yourself against your own objective
(`get_playbook("run-your-own-tournament")`). The engine's own daily selection is private.
