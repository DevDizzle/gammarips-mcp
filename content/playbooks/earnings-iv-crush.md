Status: active
Type: literature
Tag: literature-established
Exit-context: any hold that spans an earnings announcement
Source: De Silva (2026); Cao & Han (2013); GammaRips earnings-exclusion decision (literature-anchored)
Date: 2026-07-06

# Earnings IV crush — never hold long options through the print

Implied volatility inflates into earnings and collapses immediately after; a long
single-leg option can lose heavily even when the direction call is right. This is settled
in the literature and the engine deliberately never backtested it on our small N — it's a
hard exclusion at pick time.

Application: doctrine hard exclusion. Verify each candidate's earnings date against the
intended hold window yourself with `get_signal(view="earnings")` (the pool does NOT
pre-apply this rail); if the date is ambiguous, fail closed.
