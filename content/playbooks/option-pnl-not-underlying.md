Status: active
Type: finding
Tag: proven-on-cohort
Exit-context: n/a (methodology)
Source: GammaRips underlying-vs-option-PnL study
Date: 2026-07-06

# Evaluate on option PnL, never underlying direction

On the same pool, **underlying-up hit 54% while option-up hit only 41%** — theta, IV, and
spread eat a directional win. Any rule, edge, or track-record claim evaluated on
underlying direction overstates reality.

Application: every journal outcome and every wiki finding is stated in option PnL. MCP
caveat: `query_outcomes(view="signal_performance")` / `query_outcomes(view="win_rate")`
report **underlying-direction** outcomes (they carry a universe marker) — never quote them
as option performance. Option PnL lives in `query_outcomes(view="labels")` /
`query_outcomes(view="summary")` / `query_outcomes(view="surface")`.
