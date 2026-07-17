Status: active
Type: finding
Tag: policy-adopted
Exit-context: applied at decision time regardless of exit
Source: GammaRips regime rail; VIX term-structure literature (anchored, not cohort-tested)
Date: 2026-07-06

# Regime rail: VIX > VIX3M means stand down

When spot VIX trades above 3-month VIX (term-structure backwardation), the market is in
stress regime and the engine fails closed — no pick. This harness adopts the same rail:
`get_regime_context` → `regime_rail_pass = false` → no new positions that day.

It is a policy rail (literature-anchored, not backtested on our small N), which is exactly
why it's tagged policy-adopted rather than proven. Respect it anyway; fail-closed regime
discipline is cheap insurance for long-premium strategies.
