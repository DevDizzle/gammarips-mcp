Status: active
Type: methodology
Tag: architecture-fact
Exit-context: n/a
Source: GammaRips methodology
Date: 2026-07-17

# Spread is permanently retired as a selection gate

The current data plan serves **no options NBBO quotes** (bid/ask are always absent), so
`recommended_spread_pct` is permanently NULL and there is no reliable point-in-time spread
to gate on. An earlier version synthesized a fake spread from the day low/high; that was
removed once it was found to be fabricated, and the spread gate was retired entirely rather
than replaced with a bad proxy.

Contracts are therefore priced off **last-trade / day-close**, and spread is **not** a
selection criterion. Fill risk is judged instead from open interest, session volume, and
last-trade recency at the decision window (`get_liquidity`), not from a spread the data does
not support. If NBBO quotes ever return on a richer data plan, a real spread signal could be
revisited.
