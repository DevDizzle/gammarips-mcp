# Exit Lab — Exploring the Exit Space Honestly

The most important fact in this dataset: **the same pool of contracts is negative under a fixed exit and rich in favorable excursion before resolution.** Average same-day bracket outcome is negative; average max-favorable excursion (MFE) over 3 trading days is strongly positive. The gap between those two numbers *is* the product — and it's closed (or not) by exit discipline.

## The three tools

**1. `get_opportunity_surface`** — the raw material.
Per contract: `opp_peak_return` (MFE), `opp_trough_return` (MAE), minutes-to-each-extreme, over a 3-trading-day window from the 10:00 ET entry anchor, **no exit rule applied**. Fractions of entry premium (0.40 = +40%).

**2. `get_outcome_summary` / `query_outcomes`** — reference brackets, exactly simulated.
Two brackets are labeled with full engine mechanics (real fills, slippage, TIMEOUT>STOP>TARGET ambiguity handling):
- `same_day`: +40% target / −30% stop, flat 15:45 ET (the live paper-cohort policy)
- `3d`: +80% / −60%, 3-trading-day hold (legacy companion)
These are your ground truth. Any exit idea should be sanity-checked against how these *exact* labels behave in the same slice.

**3. `estimate_exit_rule`** — your bracket, classified against the surface.
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
