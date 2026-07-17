Status: active
Type: methodology
Tag: policy-adopted
Exit-context: n/a (a selection gate, not a measured edge)
Source: GammaRips methodology
Date: 2026-07-17

# BULLISH-only is a HARD gate

The pool is **hard-gated to BULLISH-only** (toggleable, but on by design). The stated
reason: the engine's edge levers are call-delta-defined and do not transfer to puts.

This is a deliberate policy override of the research caveat that "bearish is
regime-conditional, not broken" ([[bullish-direction-asymmetry]]). That direction asymmetry
was measured in one 2026 Q1/Q2 war-chop window, so the gate is an operating choice "for
now," not a claim that puts are permanently dead — but it is a hard gate today. The gate is
applied UPSTREAM, before the selection tournament ever sees the pool.
