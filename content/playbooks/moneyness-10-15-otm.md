Status: active
Type: finding
Tag: falsified-on-cohort
Exit-context: original claim on 3-day hold era labels (option PnL); re-derivation on the same 3-day era labels
Source: GammaRips moneyness study (2026-06-02); RETAGGED 2026-08-25 after the consumer-harness re-derivation (2026-07-17, n=1,806)
Date: 2026-07-06 (retagged 2026-08-25)

# 10-15% OTM was NOT the best moneyness bucket. It did not replicate

**This note previously told you to use moneyness as a secondary check. That was
wrong and it is withdrawn.** Do not filter on moneyness. Do not rank on it.

Original claim (2026-06-02, smaller and older cohort): moneyness near 10-15% OTM
outperformed nearer-the-money and deeper-OTM buckets on realized option PnL.

**Re-derivation, 2026-07-17, n=1,806 labeled 3-day rows** (scans 2026-04-13 to
2026-06-26, legacy -60/+80 bracket):

- The 10-15% bucket won 41% against the whole pool's 42%, and averaged -3.2%
  against the pool's -1.9%. There is no outperformance.
- The split-half test FLIPS SIGN: first half +6.3%, second half -9.8%. That is
  the finding. A lever that reverses across halves of its own window is noise.
- Controlled for catalyst score, the four moneyness cells cluster inside noise on
  win rate, 39% to 42%. Moneyness does not survive as an independent lever.

**This server already said so in two other places, and they were right.**
`explain_field("moneyness_pct")` states that the old 5-15% OTM gate was retired
under V6 and that moneyness is no longer a hard selection filter.
`get_playbook("changelog")` records that the legacy moneyness gate was retired
because it removed real winners. This note was the outlier.

## What moneyness is for now

Moneyness is **descriptive context**. It tells you where a strike sits. It never
filters a candidate and it never ranks one, at any band.

That rule is band-agnostic on purpose. Do not read a different band as the gate
coming back with a better number. If you want a measured lever for contract
shape, use delta ([[pool-delta-calibrated]]), and read it as a base rate rather
than as an edge.

Selection research is closed ([[selection-research-closed]]). Do not re-test this.
