Status: active
Type: methodology
Tag: policy-adopted
Exit-context: THIS NOTE DEFINES the live reference exit — same-day GIGO bracket
Source: GammaRips methodology
Date: 2026-07-17

# GIGO same-day exit — get-in-get-out, no overnight hold

The live reference exit is a same-day intraday OCO bracket:
- **Entry: 10:00 ET** on day 1 ([[entry-1000-et]]).
- **Take-profit: +40%** of option premium (limit).
- **Stop: -30%** of option premium.
- **Time-exit: flat at 15:45 ET the same day**, no trail, no overnight hold.
- On ambiguous intrabar order, resolve **TIMEOUT(15:45) > STOP > TARGET** (conservative).

The lever proven in the exit-velocity sweep was the **same-day exit itself, not the target
magnitude**: every target from +30% to "let it ride" landed ~+2.4-2.8%/trade, so same-day
is roughly tied per-trade with a multi-day hold but frees capital ~2.5x faster (~3x
return-per-capital-day) and **halves the disaster tail** (-34% vs -61%). Honest limit: the
per-trade EV improvement was NOT significant at the day level (single regime) — the case
rests on velocity + tail reduction, not higher per-trade EV.

Consequence: any edge cited to justify a live trade must be proven under this same-day
exit-context. Multi-day-hold findings (e.g. [[mom-60-conditional-lever]]) do NOT transfer.
This is ONE reference exit, not a mandate — the whole point is that the exit is a free
variable ([[fixed-exit-composites-negative]]).
