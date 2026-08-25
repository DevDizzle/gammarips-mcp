Status: active
Type: finding
Tag: falsified-on-cohort
Exit-context: same-day V7.1 replay (10:00 fill x 1.02 / +40% TP / -30% stop / 15:45 flat, real print at both anchors) and same-day MFE/MAE from a 10:00 fill
Source: GammaRips pre-registered studies, 2026-08-22 (pool-vs-benchmark, 87 days; liquid-universe funnel, 57 days)
Date: 2026-08-22

# The pool is not a selection edge. We tested it and it failed

This is the most important thing to know before you build on this data, and it is
the uncomfortable one. **Pool membership does not predict returns.** We ran two
pre-registered tests, each with its decision rules written before any data was
pulled, and all of them failed.

**Study 1, pool against benchmark, 87 days.** The production pool against
liquidity-and-sector-matched controls and against random optionable controls,
with the same contract rule in every arm. Mean same-day return: pool **-7.72%**,
matched **-6.40%**, random **-7.23%**. H1 pool-minus-matched -1.33pp
[-3.78, 1.04]. H2 median-MFE -1.57pp [-4.25, 0.92]. H3 pool-minus-random -0.50pp
[-4.75, 3.84]. All three fail.

**Study 2, liquid-universe funnel, 57 days, 545 legs.** Inside the top-100 liquid
names, a call-dollar-volume z-score >= 2.0 against each name's own 20-session
baseline, against 200 seeded draws of liquidity-matched random names with the same
contract rule. Same-day median MFE **14.0% against 13.6%**, +0.4pp, 90% CI
[-1.7, 2.1]. Both half-windows null.

**Read the power limit honestly.** These tests detect about 5pp per trade. They
cannot detect 1 to 2pp. So the correct statement is "no large edge", never
"no edge". A small edge is not excluded. It is also not something we will claim.

## What this means for you

- Do not treat pool membership as evidence a contract is good. Treat the pool as
  a liquid, tradeable universe and nothing more.
- Do not look for the ranking inside the pool. There isn't one that survived
  testing. Earlier candidates that failed: [[moneyness-10-15-otm]],
  [[voi-ratio-anti-edge]], [[oi-not-quality-signal]],
  [[ride-winners-mean-reverts]].
- The open question is whether **your** screen beats the pool it draws from. We
  did not test that and cannot. Only your own scored funnel can answer it, and
  scoring only the names you traded cannot: you have to score the ones you passed
  over too.

## What DID measurably improve

Executability, and only executability. The liquid universe took no-fill at
10:00 ET from **40.5% to 6.1%** and tradeable-by-10:00 from **17.9% to 63.1%**,
against the old production pool on the same tape. The random control matches
those numbers, so the gain belongs to the universe rule, not to a signal.

That is the honest product: contracts your agent can get into and out of, plus
the realized opportunity surface to reason over. The exit is where the money is
([[fixed-exit-composites-negative]]).
