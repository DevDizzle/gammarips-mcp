Status: active
Type: finding
Tag: proven-on-cohort
Exit-context: 3-trading-day window from the 10:00 day-1 entry, real option minute bars, touch-based ceiling (limit-touch ≠ fill)
Source: GammaRips harvest-curve retro, N=2,029 (2026-07-06 retro #3)
Date: 2026-07-06

# The 3-day harvest curve — real, late, and not rule-able

> **Cohort bound (2026-08-25):** measured on the pre-2026-08-25 pool, which was selected
> on unusual activity. The funnel now selects on liquidity. The curve held on the
> population it was tested on. It is a property of the contracts, NOT evidence that pool
> membership causes the pop: a pre-registered study on 2026-08-22 found the pool
> indistinguishable from matched random optionable contracts ([[selection-research-closed]]).

Within 3 days of entry the excursion on these contracts is real: **P(touch +20%) = 51%,
+50% = 31%, +100% = 14%; median peak +21%**. But three corrections to the "get in day 1,
take your target" intuition:

1. **The pop comes LATE.** Given a peak ≥ +20%, it lands day-1 only 15% of the time,
   day-3 52%. Only 9% of the pool clears +15% on day one. Plan for day 2–3, not hours.
2. **A fixed target is EV-negative at every level** (−7.2%/trade at +20%, −2.4% at +80%,
   pool-wide): the half that never pops loses ~35% by window end, and cheap targets
   amputate the right tail that pays for them. EV improves monotonically with the target.
3. **Half of all paths touch −30% first-or-eventually** (P(trough ≤ −30%) = 50.6%) —
   size and stomach for that, or the stop harvests you.

**The one positive-EV lead: tournament picks** (N=24, all eras) — rule EV positive at
every target ≥ +20 (+11% at +75/80), hold-to-window-end +10.3%, WR 54%. CIs vs pool span
zero, so this is a lead to accrue toward N≥30, never load-bearing yet. (The "V7.1-era
N=2" figure previously quoted here was keyed on the policy LABEL alone; under the
corrected cohort definition — label AND entry on/after 2026-08-10 — live-cohort N is 0.
Anchor era claims to an explicit date range, never the bare label. See
`get_playbook("changelog")`.)
The mom_60 tilt's harvest lift failed walk-forward (regime) — consistent with
[[mom-60-conditional-lever]]. Canonical exit-is-the-problem exhibit: a name that peaked
+1,234% on day 3 while the live same-day exit realized −47.8% on the same path
([[fixed-exit-composites-negative]]).

Application: theses may cite the harvest curve as the base rate for target feasibility;
never as "reliable pop." Exit plans that cap at +15/20% by default contradict the
measured shape; late-window patience with drawdown tolerance fits it.
