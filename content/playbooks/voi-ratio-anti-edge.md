Status: active
Type: finding
Tag: falsified-on-cohort
Exit-context: 3-day hold era labels (option PnL)
Source: GammaRips flow-conviction (V/OI) study, H16 (2026-06-02)
Date: 2026-07-06

# Volume/OI ratio filters — falsified

Requiring `V/OI > 2` (the classic "fresh positioning" screen) did NOT improve selection on
our cohort — it **removed winners**. The intuition that a high volume-to-OI ratio marks
new conviction flow did not survive contact with realized option PnL here.

Application: never use V/OI as a screen or a tiebreaker. Related: the underlying data is
session-frozen anyway ([[oi-not-quality-signal]]), so the ratio is doubly untrustworthy at
decision time.
