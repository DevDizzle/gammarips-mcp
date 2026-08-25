Exit-context: MIXED — every numbered finding below states its own horizon. Items 1, 2 and 6 are to-expiry. Items 3, 4 and 5 are the 3-trading-day window from the 10:00 ET entry. Do not read a number here without its horizon.
Cohort: all figures below were measured on the pre-2026-08-25 pool, selected on unusual activity. The funnel now selects on liquidity.

# Exit Lab — Exploring the Exit Space Honestly

The most important fact in this dataset: **the same pool of contracts is negative under a fixed exit and rich in favorable excursion before resolution.** Average same-day bracket outcome is negative; average max-favorable excursion (MFE) over 3 trading days is strongly positive. The gap between those two numbers *is* the product — and it's closed (or not) by exit discipline.

## What the surface actually says — measured, 2026-07-06

Three pre-registered studies: two on every expired pool contract (N=2,146 and
N=1,303; scans 2026-04-10 through 2026-06-30) and one on every closed 3-day
excursion window (N=2,029; scans through 2026-06-26). Single Apr-Jun regime
arc — these re-run as eras accrue. The
numbers below include the unflattering ones on purpose; that is the point of
a research subscription.

1. **Delta is your base rate.** *(to-expiry)* Realized ITM-at-expiration was
   41.3% vs a mean scan-time |delta| of 42.1% (N=2,146). The pool converts to
   ITM at the market-implied rate — selection curates *which* fairly-priced
   contracts you see; it does not find direction the market missed. That last
   clause is a principle and holds under any hold period. The 41.3% does not:
   it is an at-expiration number.
2. **The path is fairly priced too.** Realized excursion peaks sit at the
   ~51st percentile of each contract's own entry-IV-implied distribution
   (N=1,303). The peaks are big (p90 peak ≈ +445% to expiry) — and exactly as
   big as the IV charged.
3. **The harvest curve** (3-trading-day window, touch-based ceiling, N=2,029):
   P(touch +15%) = 55%, +20% = 51%, +50% = 31%, +100% = 14%; median peak +21%.
   Serve it live, with your own filters, via `get_harvest_curve`.
4. **The pops come late.** *(3-trading-day window)* Given a peak ≥ +20%, it
   lands day 1 only ~15% of the time and day 3 ~52%. "Take a quick profit hours
   after entry" is the exception, not the pattern. Note that the live paper
   policy exits same day, so this finding describes a window wider than that
   policy uses.
5. **Fixed targets tested EV-negative at every level** *(3-trading-day window)*
   (−7.2%/trade at +20%,
   still −2.4% at +80%): the ~half that never pops loses ~35% by window end,
   and a cheap target amputates the right tail that pays for it. EV improves
   monotonically as the target rises. Also: a −30% drawdown is touched on
   ~51% of all paths — size for it or your stop harvests you.
6. **The giveback is the product.** Conditional on touching +50%, the median
   contract retained only 31% of its peak at expiration; ~48% of all
   ever-profitable contracts expired at a loss. The surface is real; holding
   to expiry surrenders most of it. What closes that gap — or doesn't — is
   your exit.

Caveats that always apply: touches are bar-high events, not fills (no exit
slippage in the surface); the ~28% illiquid/unlabeled tail is excluded and
non-random; one regime arc so far.

## The four tools

**1. `get_opportunity_surface`** — the raw material.
Per contract: `opp_peak_return` (MFE), `opp_trough_return` (MAE), minutes-to-each-extreme, over a 3-trading-day window from the 10:00 ET entry anchor, **no exit rule applied**. Fractions of entry premium (0.40 = +40%).

**2. `get_outcome_summary` / `query_outcomes`** — reference brackets, exactly simulated.
Two brackets are labeled with full engine mechanics (real fills, slippage, TIMEOUT>STOP>TARGET ambiguity handling):
- `same_day`: +40% target / −30% stop, flat 15:45 ET (the live paper-cohort policy)
- `3d`: +80% / −60%, 3-trading-day hold (legacy companion)
These are your ground truth. Any exit idea should be sanity-checked against how these *exact* labels behave in the same slice.

**3. `get_harvest_curve`** — the touch probabilities, live.
For your target grid (and optional delta/date filters): P(peak ≥ X) with
confidence intervals, which day the peak lands on, and stop-touch rates.
Computed fresh from the substrate on every call, so it moves as data accrues.

**4. `estimate_exit_rule`** — your bracket, classified against the surface.
For an arbitrary (target, stop), each contract is classified TARGET / STOP / TIMEOUT from its extremes. Read the output critically:

- **Definitive rows** (only one level crossed) are exact.
- **`*_HEURISTIC` rows** — both levels crossed inside the window. The surface stores *extremes*, not the path, so first-crossing order is unrecoverable; the row is resolved by which extreme came first and tagged. **Always check `heuristic_share`** — if it's large for your bracket (tight targets + tight stops make it large), treat the estimate as soft and lean on `est_win_rate_definitive_only` and the EV bounds instead.
- **TIMEOUT rows** — neither level hit. The window-end price isn't stored, so their true return is only bounded by [avg MAE, avg MFE]. This is why the tool returns `ev_bounds` rather than one EV number.
- **No exit slippage** is applied to surface estimates. The exact labels include it; expect your realized results to sit below surface estimates.

## An honest exploration loop
1. Start from the exact labels: `get_outcome_summary(horizon="same_day")` and `horizon="3d"` — the two known points in the exit space.
2. Sweep brackets with `estimate_exit_rule` (e.g. targets 20–120%, stops −20 to −60%), recording `ev_bounds` and `heuristic_share` for each.
3. Slice, don't average: repeat within feature slices via `query_outcomes` filters (e.g. |delta| 0.20–0.46 — the strongest historical lever). Pool-wide EV hides the conditional structure that matters.
4. Distrust anything that only works in one 2-week window. The pool is ~50 rows/day and regime-sensitive; demand stability across sub-periods before believing an edge.
5. Remember what's excluded: ~28% of pool rows have no label (illiquid at the entry anchor) and that tail is non-random. Exclusion counts are in every response's `meta` — quote them alongside any conclusion.

## What we'd tell a friend
Selection gets you a lottery ticket with better-than-lottery odds; the exit decides whether you ever cash one. Fixed "set and forget" brackets underperform what the excursion structure makes available — that's precisely why this server sells the surface and leaves the exit to you.
