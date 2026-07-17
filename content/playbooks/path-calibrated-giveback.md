Status: active
Type: finding
Tag: proven-on-cohort
Exit-context: intrinsic-bound path, 10:00 entry through expiration (N=1,303 expired calls); option-price path timing still unmeasured (needs the follow collector)
Source: GammaRips excursion-vs-IV retro (2026-07-06 retro #2)
Date: 2026-07-06

# The pool is path-calibrated to its own IV — the giveback is the edge surface

Companion to [[pool-delta-calibrated]]. Realized excursion peaks sit at the **50.95th
percentile** of each contract's own entry-IV-implied distribution (CI straddles 0.5; KS
p=0.50): the pool's big peaks (p90 +445%, 36% touch +100%) are **exactly as big as the IV
priced** — no fatness anomaly. Peak **timing** also matches the null on the intrinsic
bound: median peak arrives **day 7 of a 10-day life** (back third), P(peak within 3 days)
= 19.5% ≈ implied. Caveat: the bound late-biases true option-price peaks (theta), so
early-peaking in option prices is unrefuted-but-unproven until the to-expiration collector
exists.

**The durable, verified fact is the giveback:** conditional on touching +50%, the median
contract retains only **31% of its peak** at expiry and 37.8% round-trip to a loss; 48.5%
of ever-profitable contracts die at a loss.

Application: (1) treat entry IV as the honest excursion base rate — never claim or assume
the pool "moves more than priced"; (2) the enter-day-1/exit-at-the-peak intent is
NOT supported by early peaks on underlying paths — peaks cluster LATE, so near-term exits
catch ~1 in 5 peaks; patience through most of the life, then harvesting before expiry
bleed, fits the measured shape better; (3) the thing a disciplined exit harvests is the
giveback, and it is large.
