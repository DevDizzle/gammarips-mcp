Status: active
Type: finding
Tag: proven-on-cohort
Exit-context: 3-day hold, −60%/+80% bracket era labels (option PnL)
Source: GammaRips internal cohort study (direction / flow-intent)
Date: 2026-07-06

# Bullish direction asymmetry

On the labeled cohort, BULLISH signals averaged **+4.11% per trade** while BEARISH averaged
**−7.71%** on option PnL — direction was the single most robust EV separator found, and the
reason the engine hard-gates the pool to BULLISH-only.

Caveats: the bearish leg was measured in the 2026 Q1/Q2 war-chop regime, so "bearish is
broken" is regime-conditional in principle; and the numbers are 3-day-hold era. For this
harness the practical rule is simple: long bullish candidates only (the pool is
BULLISH-only anyway), and don't extrapolate the asymmetry to other exits without checking
[[fixed-exit-composites-negative]].
