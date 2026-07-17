Status: active
Type: finding
Tag: proven-on-cohort
Exit-context: fixed same-day GIGO bracket (10:00 entry, +40/−30, flat 15:45) applied uniformly to the whole pool
Source: GammaRips pool-composite studies 2026-06/07 (3,094-contract / 54-day seed)
Date: 2026-07-06

# Fixed-exit pool composites are negative; the exit is the free variable

Blind-buying the ENTIRE curated pool under the fixed GIGO exit loses **≈ −2 to −6% per day
(−4.4%/day on the 3,094-contract / 54-day seed) at ~30% win rate**, robust across
walk-forward. Yet the same pool's opportunity surface is real: **median intraday peak
+21%, p90 +123%, median trough −30.5%** — contracts run hard and give it back to a fixed
bracket (07-01 finalists hit +47%/+179% intraday before the fixed exit surrendered it).

The conclusion that reorganized the whole product: **the contracts are good, the
hard-coded exit was the problem.** Profitability lives in HOW a surfaced contract is
traded — selection of WHICH candidates, and a deliberately designed exit.

Application: never trade the pool blind; never adopt a bracket by default. `/exit-plan`
designs the exit per-trade from `query_outcomes(view="surface")` +
`query_outcomes(view="exit_rule")`. This is also why no whole-pool composite may ever be
cited as a strategy return.
