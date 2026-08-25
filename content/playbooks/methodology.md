# Methodology & Findings — the claim-tagged corpus

Atomic, claim-tagged methodology notes: how the curated pool is built and why, plus what is
proven / falsified / fragile on the GammaRips cohorts and what the external literature
settles. One claim per note. Fetch any with `get_playbook(name="<slug>")`.

Tags: `proven-on-cohort` (held up on labeled data, still era-bound) - `falsified-on-cohort`
(tested and rejected — an anti-edge, as valuable as a proven one) - `fragile-conditional`
(survived only under specific conditions; proposer-only) - `literature-established` (settled
in published research, deliberately not re-tested on small N) - `policy-adopted` (an
operating rule we run) - `architecture-fact` (a data-contract / pipeline fact). Every edge
is **exit-conditional** — read each note's `Exit-context` before citing it.

## Selection & methodology policy — how the pool is built and why
- [[enrichment-definition]] — policy-adopted — "enriched" = overnight_score >= 1 (a cosmetic floor) + directional UOA > $500K
- [[bullish-only-hard-gate]] — policy-adopted — the pool is hard-gated BULLISH-only (call-delta levers don't transfer to puts)
- [[tourney-pool-cap-edge-rank]] — policy-adopted — soft edge-rank (delta / RR / ATR) then cap, before the tournament
- [[bracket-tournament-selection]] — policy-adopted — one signal/day or none via a 3-bracket randomized tournament (consensus 3/3=high; no memory/rubric; fail-closed)
- [[gigo-same-day-exit]] — policy-adopted — reference exit: 10:00 entry / +40% TP / -30% stop / flat 15:45 ET, no overnight
- [[earnings-exclusion-rail]] — policy-adopted — safety rail 1: no earnings in the hold/exclusion window (literature-anchored)
- [[regime-rail-vix-term]] — policy-adopted — safety rail 2: VIX > VIX3M (backwardation) = stand down
- [[leakage-safety-gate]] — policy-adopted — every candidate is leakage-checked before selection; the one non-negotiable
- [[spread-gate-retired]] — architecture-fact — no NBBO on the current data plan; spread is permanently retired as a gate
- [[opportunity-surface]] — architecture-fact — MFE/MAE excursions recorded with NO exit applied, so the exit stays a free variable

## Findings — tested on our cohorts
- [[bullish-direction-asymmetry]] — architecture-fact — the reason the funnel is bullish-only (+4.11 vs -7.71/trade, 3-day era); the pool holds no bearish arm now, so this is not re-runnable in-pool and is not a selector
- [[delta-band-0-20-0-46]] — proven-on-cohort — mid |delta| 0.20-0.46 is the only feature separating winners from losers
- [[option-pnl-not-underlying]] — proven-on-cohort — evaluate on option PnL, never underlying direction (54% vs 41%)
- [[fixed-exit-composites-negative]] — proven-on-cohort — the whole pool under any fixed exit is negative; the exit is the free variable
- [[pool-delta-calibrated]] — proven-on-cohort — pool expires ITM at the delta-implied rate; zero directional alpha, all ROI is in the trading layer
- [[path-calibrated-giveback]] — proven-on-cohort — excursion peaks match entry IV and arrive LATE; the verified edge surface is the giveback
- [[three-day-harvest-curve]] — proven-on-cohort — P(touch +20% in 3d)=51%, pops land day 2-3, fixed targets are EV-negative pool-wide
- [[selection-research-closed]] — falsified-on-cohort — READ THIS FIRST: the pool is indistinguishable from matched random optionable contracts (2 pre-registered studies, 87 and 57 days); pool membership is not evidence a contract is good
- [[moneyness-10-15-otm]] — falsified-on-cohort — did NOT replicate (n=1,806, halves flip sign); moneyness is descriptive only and never filters or ranks, at any band
- [[mom-60-conditional-lever]] — fragile-conditional — 60-day momentum x delta band works ONLY multi-day; zero edge same-day
- [[voi-ratio-anti-edge]] — falsified-on-cohort — V/OI > 2 filters remove winners
- [[oi-not-quality-signal]] — falsified-on-cohort — higher OI monotonically worse; OI/volume are session-frozen anyway
- [[ride-winners-mean-reverts]] — falsified-on-cohort — recent option-winner persistence is an anti-edge
- [[entry-1000-et]] — policy-adopted — enter ~10:00 ET, not at the open

## Literature — external, not tested on our data
- [[earnings-iv-crush]] — literature-established — never hold long single-leg options through earnings
- [[position-sizing-basics]] — literature-established — fixed-fractional small risk per trade; Kelly overbets on fat-tailed option outcomes
