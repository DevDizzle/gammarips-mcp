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

## Access tiers

Works with **no API key** (free tier): `get_daily_report`, `get_report_list`,
`get_freemium_preview`, `list_playbooks`, `get_playbook`,
`get_signal_explainer`, `get_market_calendar_status`, `get_available_dates`.

Everything else (the full pool, features, surfaces, outcomes) requires a
`gr_live_...` key sent as `Authorization: Bearer <key>` — Agent Access at
https://gammarips.com/pricing. If a pro tool returns `subscription_required`,
tell the user how to add the key; do not retry.

## Recommended workflow

1. **Orient.** First session: `get_playbook("start-here")`, then
   `get_playbook("daily-workflow")`. Check `get_market_calendar_status` and
   `get_available_dates` before assuming today has data.
2. **Read the day.** `get_daily_report` for the editorial synthesis;
   `get_enriched_signals` (pro) for the curated pool with narratives,
   technicals, catalysts, and the recommended contract per name.
3. **Go deep on candidates.** `get_signal_detail` for one ticker;
   `get_pool_features` for the leakage-safe feature vectors;
   `get_contract_snapshot` for fresh entry-day open interest and session volume.
4. **Study the opportunity, not a promise.** `get_opportunity_surface` shows
   what each contract *realized* (MFE/MAE, exit-free). `get_harvest_curve`
   gives touch probabilities for profit levels; `query_outcomes` /
   `get_outcome_summary` give bracket labels; `estimate_exit_rule` classifies
   YOUR (target, stop) bracket against history. `get_regime_context` for the
   VIX/VIX3M regime rail.
5. **Synthesize your own thesis.** Pick (or decline) a contract and exit from
   the evidence, state your reasoning, and label it as your analysis of
   research data.

## Hard rules for using this data honestly

- **Point-in-time discipline.** Features are as-of the overnight scan; outcome
  labels and surfaces arrive T+1 after the trade window closes. Never treat a
  label or surface as a live signal for the same day. When unsure what a field
  is, check `get_enriched_signal_schema` (every column carries a leakage
  classification) or `get_signal_explainer`.
- **The honest baseline.** Blind-buying the whole pool under one fixed exit
  has a negative historical composite — GammaRips publishes this deliberately.
  The surfaces show *potential*; whether it is harvested depends on contract
  selection and exit management. Never quote pool-level stats as an expected
  return.
- **Receipts vs. direction.** `get_position_history` /
  `get_historical_performance` are realized paper-trade receipts (option PnL).
  `get_signal_performance` / `get_win_rate_summary` are underlying-stock
  direction outcomes — do not conflate the two.
- No performance promises, no "GammaRips says buy X". Data, not advice.
