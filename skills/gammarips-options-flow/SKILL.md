---
name: gammarips-options-flow
description: Workflow for the GammaRips options-flow MCP server — read the curated daily pool, point-in-time features, realized MFE/MAE opportunity surfaces, and outcome labels, then reason toward YOUR OWN contract and exit. Use when the user asks about unusual options activity, the GammaRips pool, opportunity surfaces, or options-flow research data.
---

# GammaRips options-flow analysis

GammaRips is an anti-firehose options-flow **data vendor**, not a signal service.
Every trading morning (~05:30 ET) its engine scans ~5,000 US equities for unusual
options activity and curates hard — down to a small high-signal BULLISH candidate
pool with point-in-time features, realized **opportunity surfaces** (max-favorable /
max-adverse excursions with no exit applied), bracket outcome labels, and
methodology playbooks.

**The contract of this data: there is no pick endpoint.** The server hands you
primitives; you reason from them to your own contract and your own exit. Never
present its output as a recommendation from GammaRips — it is paper-traded
research data, educational only, not investment advice. Say so when you
summarize results for the user.

The surface is **9 tools**, each with `view=`/`granularity=` modes — discover it
live: `get_playbook()` lists the workflow playbooks and the methodology corpus,
and `get_playbook("methodology")` explains how the pool is built and why.

## Access tiers

Works with **no API key** (free tier): `get_pool(view="preview")` (the pool
teaser), `get_daily_report`, `get_regime_context`, `get_market_calendar_status`,
and `get_playbook` (methodology pages, the field dictionary via `field="..."`,
and the data-contract schema via `name="schema"`).

Everything else — the full pool (`get_pool` with `view="enriched"|"raw"|"features"`),
`get_signal`, `get_liquidity`, `query_outcomes`, and `replay_contract` — requires
a `gr_live_...` key sent as `Authorization: Bearer <key>` (Agent Access at
https://gammarips.com/pricing). If a pro tool or view returns
`subscription_required`, tell the user how to add the key; do not retry.

## Recommended workflow

1. **Orient.** First session: `get_playbook("start-here")`, then
   `get_playbook("daily-workflow")`, and `get_playbook("methodology")` for the
   selection logic. Check `get_market_calendar_status` (and
   `get_market_calendar_status(view="scan_dates")` for which dates have data)
   before assuming today has a pool.
2. **Read the day.** `get_daily_report` for the editorial synthesis;
   `get_pool(view="enriched")` (pro) for the curated pool with narratives,
   technicals, catalysts, and the recommended contract per name.
3. **Go deep on candidates.** `get_signal(view="detail")` for one ticker
   (`view="earnings"` for its earnings-window check); `get_pool(view="features")`
   for the leakage-safe feature vectors; `get_liquidity(contract=...)` for fresh
   entry-day open interest and session volume.
4. **Study the opportunity, not a promise.** `query_outcomes(view="surface")`
   shows what each contract *realized* (MFE/MAE, exit-free);
   `query_outcomes(view="harvest")` gives touch probabilities for profit levels;
   `query_outcomes(view="labels")` / `query_outcomes(view="summary")` give bracket
   labels; `query_outcomes(view="exit_rule")` scores YOUR (target, stop) bracket
   against history; `replay_contract` returns the raw price tape for your own rule.
   `get_regime_context` for the VIX/VIX3M regime rail.
5. **Synthesize your own thesis.** Pick (or decline) a contract and exit from
   the evidence, state your reasoning, and label it as your analysis of
   research data.

## Hard rules for using this data honestly

- **Point-in-time discipline.** Features are as-of the overnight scan; outcome
  labels and surfaces arrive T+1 after the trade window closes. Never treat a
  label or surface as a live signal for the same day. When unsure what a field
  is, check `get_playbook(name="schema")` (every column carries a leakage
  classification) or `get_playbook(field="<name>")`.
- **The honest baseline.** Blind-buying the whole pool under one fixed exit
  has a negative historical composite — GammaRips publishes this deliberately.
  The surfaces show *potential*; whether it is harvested depends on contract
  selection and exit management. Never quote pool-level stats as an expected
  return.
- **Receipts vs. direction.** `query_outcomes(view="positions")` /
  `query_outcomes(view="performance")` are realized paper-trade receipts (option
  PnL). `query_outcomes(view="signal_performance")` / `query_outcomes(view="win_rate")`
  are underlying-stock direction outcomes — do not conflate the two.
- No performance promises, no "GammaRips says buy X". Data, not advice.
