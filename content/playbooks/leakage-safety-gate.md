Status: active
Type: methodology
Tag: policy-adopted
Exit-context: n/a
Source: GammaRips methodology
Date: 2026-07-17

# Every candidate is leakage-checked before selection — the one non-negotiable

Every candidate passes a fail-closed **leakage-safety check** before it reaches the
selection tournament: a candidate that cannot be shown leakage-clean is dropped, never
selected. Leakage-safety is the program's one non-negotiable — it is physics, not policy,
and it is never waivable (unlike the out-of-sample validation ceremony, which is an owner
call).

This is why point-in-time discipline is enforced everywhere upstream: technical-indicator
windows are bounded to the scan date, the regime feature is measured as-of the scan-date
close, and session-frozen OI/volume are walled off from the selection model
([[oi-not-quality-signal]]). The machine-readable, column-by-column contract — which fields
are `feature` (knowable at <= scan_date, the only class usable as a selection input) versus
`label` / `opportunity` / `regime_telemetry` (realized post-entry) — is in
`get_playbook("leakage-and-data-contract")` and `get_playbook(name="schema")`.
