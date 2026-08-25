Status: active
Type: finding
Tag: proven-on-cohort
Exit-context: fixed same-day GIGO bracket (10:00 entry, +40/−30, flat 15:45) applied uniformly to the whole pool
Source: GammaRips pool-composite studies 2026-06/07 (3,094-contract / 54-day seed)
Date: 2026-07-06

# Fixed-exit pool composites are negative; the exit is the free variable

Blind-buying the ENTIRE curated pool under the fixed GIGO exit loses **≈ −2 to −6% per day
(−4.4%/day on the 3,094-contract / 54-day seed) at ~30% win rate**, robust across
walk-forward. Yet the excursion surface on those same contracts is real: **median intraday
peak +21%, p90 +123%, median trough −30.5%** — contracts run hard and give it back to a
fixed bracket (07-01 finalists hit +47%/+179% intraday before the fixed exit surrendered
it).

**Cohort bound (added 2026-08-25):** measured on the pre-2026-08-25 pool, which was
selected on unusual activity. The funnel now selects on liquidity. These figures held on
the population they were tested on. They say nothing about today's pool.

The conclusion that reorganized the whole product: **the excursion is real and the
hard-coded exit was the problem.** The exit half of that is measured. The selection half
is NOT. A pre-registered study on 2026-08-22 found the pool indistinguishable from matched
random optionable contracts on the same tape, so pool membership is not a demonstrated
profitability lever ([[selection-research-closed]]). Whether your own screen beats the pool
it draws from is an open question that only your own scored funnel can answer.

Application: never trade the pool blind; never adopt a bracket by default. `/exit-plan`
designs the exit per-trade from `query_outcomes(view="surface")` +
`query_outcomes(view="exit_rule")`. This is also why no whole-pool composite may ever be
cited as a strategy return.
