Status: active
Type: literature
Tag: literature-established
Exit-context: n/a (risk management)
Source: standard risk-management literature (fixed-fractional sizing; Kelly criterion caveats)
Date: 2026-07-06

# Position sizing for long options — small, fixed-fractional, never Kelly-full

Long OTM options are fat-tailed: most trades lose most of their premium, occasional trades
pay multiples. Standard practice for such distributions: **fixed-fractional risk of a small
percentage of the account per trade, sized on full-premium loss**, because the realized
loss on a long option is frequently ~100% of premium. Full-Kelly sizing systematically
overbets when the payoff distribution is estimated from small samples (our situation
permanently), and drawdown-driven abandonment — not EV — is the usual practical failure
mode.

Application: doctrine encodes fixed-fractional paper sizing you set for yourself. Practice
the arithmetic in every journal entry: "if this were a $X account, this trade risks Y%."
