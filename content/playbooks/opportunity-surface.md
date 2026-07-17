Status: active
Type: methodology
Tag: architecture-fact
Exit-context: the surface captures MFE/MAE so the exit stays a free variable
Source: GammaRips methodology
Date: 2026-07-17

# The opportunity surface — MFE/MAE with the exit left free

The engine keeps a leakage-safe, OPTION-level research substrate: a lagged daily replay
runs the reference bracket over the full enriched BULLISH pool (~50 names/day), so edge
tests run on CURRENT data and keep growing (the frozen 1,375-trade study could not —
[[option-pnl-not-underlying]]).

Two things it records: (1) the **opportunity surface** — each contract's realized
max-favorable / max-adverse excursion (MFE/MAE) over the window with **NO exit applied**, so
the EXIT is a free variable rather than baked in; and (2) the point-in-time `mom_60`
momentum feature, so that lever ([[mom-60-conditional-lever]]) stays replayable. This is the
mechanical embodiment of "surface good contracts; profit depends on how they're traded"
([[fixed-exit-composites-negative]]).

Application: `query_outcomes(view="surface")` returns the excursion structure; score your
own exit against it with `query_outcomes(view="exit_rule")`. The whole-pool composite under
any one fixed exit is negative — the surface is a research object, never a strategy return.
