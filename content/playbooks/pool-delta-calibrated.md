Status: active
Type: finding
Tag: proven-on-cohort
Exit-context: hold-to-expiration, zero discretion (enter 10:00 entry-day, collect intrinsic at expiry)
Source: GammaRips ITM-vs-delta retro, N=2,146 expired (2026-07-06; pre-committed H1 rejected)
Date: 2026-07-06

# The pool is delta-calibrated — no directional edge at expiration

Pre-committed test: do pool contracts expire ITM more often than their scan-time |delta|
(the market-implied probability) says they should? **No.** ITM 41.3% vs mean δ 42.1%
(N=2,146; cleaned of a delta-data bug: 40.9% vs 42.9%). Calibration is near-perfect in
every delta bucket, and the study window was a violently bullish tape that should have
flattered a long-call pool. Adjusting for N(d1) overstating true P(ITM), the read is
**exactly zero directional alpha, not negative**. Companion floor: hold-to-exp ROI has
mean +15.6% but median −100%, 60% expire worthless — the mean is top-10-trade and
April-regime dependent, never load-bearing.

Application — this note recalibrates every thesis: the scanner surfaces *fairly-priced*,
high-excursion, curated contracts; it does NOT find direction the market missed. A thesis
may never claim "the pool wins by being right on direction." Whatever return this harness
earns must come from selection-within-pool, entry timing, and the exit — the layers this
harness exists to practice ([[fixed-exit-composites-negative]]). Treat delta itself as the
honest base rate for P(profit potential realizing): a 0.35-delta candidate is a ~1-in-3
proposition at expiry no matter how good the narrative reads. Era caveat: the post-06-12
top-50 era reads worse (−21pp) on a structurally biased N=68 — re-check ~mid-August.
