Status: active
Type: methodology
Tag: policy-adopted
Exit-context: any hold that spans a scheduled earnings print
Source: GammaRips methodology; De Silva/Smith/So (2026); Cao & Han (2013)
Date: 2026-07-17

# Safety rail 1 — no earnings in the hold/exclusion window

The engine hard-excludes any candidate whose scheduled earnings date falls inside the
intended hold/exclusion window. It walks the ranked candidates and takes the first
non-overlapping name; if every candidate overlaps, it stands down for the day. Fail-closed
on a calendar-fetch failure or an unusable payload.

This is a **literature-anchored EXCLUSION rule, not a selection gate** — implied volatility
inflates into earnings and crushes immediately after, so a long single-leg option loses
even when the direction call is right ([[earnings-iv-crush]]). It is deliberately NOT
backtested on our small N; the literature settled it at a scale we cannot match. It is one
of exactly two safety rails ([[regime-rail-vix-term]] is the other); everything else was
removed from selection.

Application: the pool does NOT pre-apply this rail — verify each candidate's earnings date
against your intended hold yourself (`get_signal(view="earnings")`), and if the date is
ambiguous, fail closed.
