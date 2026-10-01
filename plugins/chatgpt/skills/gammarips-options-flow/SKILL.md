---
name: gammarips-options-flow
description: Use the GammaRips options-flow data (the nightly liquidity-ranked pool, point-in-time features, realized MFE/MAE opportunity surfaces, outcome labels, regime, and methodology) to answer questions about US options flow. Use when the user asks about the GammaRips pool, unusual options activity, opportunity surfaces, or options-flow research data. Never returns a pick.
---

# GammaRips options-flow data

GammaRips is an options-flow **data vendor**, not a signal service. Every US
trading night it ranks about 3,500 optionable US stocks by liquidity, keeps the
100 most liquid, keeps the bullish names, and prices one out-of-the-money call
in each. That gives a pool of roughly 40 to 50 contracts with point-in-time
features, realized **opportunity surfaces** (maximum favorable and maximum
adverse excursion, with no exit applied), bracket outcome labels, and
methodology playbooks.

GammaRips does not claim these are the best contracts. Two pre-registered
studies found the pool indistinguishable from matched random optionable
contracts. The liquidity rule makes the contracts easier to fill. It does not
make them better.

## Rules

- **There is no pick.** Never present a tool result as a GammaRips
  recommendation. If the user asks what to buy, show the relevant data and
  say that the conclusion is theirs.
- **No promised returns.** Never quote a pool statistic as an expected return.
  The whole pool traded under any one fixed exit has a negative historical
  average, and GammaRips publishes that.
- **Point-in-time discipline.** Features are as of the overnight scan. Outcome
  labels and surfaces arrive after the trade window closes. Never treat a label
  or a surface as a live signal for the same day. If you are not sure when a
  field was knowable, call `get_playbook(name="schema")` or
  `get_playbook(field="<name>")`.
- **No trades.** GammaRips is read-only. It cannot place, change, or cancel an
  order. Say so if the user asks.
- When you summarize results, say that they are paper-traded research data,
  educational only, and not investment advice.

## Plans

The preview pool (`get_pool(view="preview")`), `get_daily_report`,
`get_regime_context`, `get_market_calendar_status`, and `get_playbook` are on
every GammaRips plan. The full pool (`get_pool` with `view="enriched"`, `"raw"`,
or `"features"`), `get_signal`, `get_liquidity`, `query_outcomes`, and
`replay_contract` need GammaRips Pro. If a tool returns
`subscription_required`, tell the user that the feature is not included in
their current plan. Do not retry the call.

## Workflow

1. **Orient.** On a first question, call `get_playbook(name="start-here")`.
   Before you use the pool, call `get_market_calendar_status(view="freshness")`.
   `fresh` is false when the pool is stale or empty, or when a check could not
   run.
2. **Read the day.** `get_daily_report` for the written summary.
   `get_pool(view="enriched")` for the pool with thesis, technicals, catalyst,
   and the selected contract for each name.
3. **Go deep on one name.** `get_signal(view="detail")` for one ticker, and
   `view="earnings"` for its earnings-window check. `get_liquidity(contract=...)`
   for fresh open interest and session volume.
4. **Study what happened, not a promise.** `query_outcomes(view="surface")`
   for realized MFE and MAE. `view="harvest"` for touch probabilities.
   `view="labels"` or `view="summary"` for bracket labels. `view="exit_rule"`
   scores a target and stop the user chooses against history.
   `replay_contract` returns the price tape. `get_regime_context` gives the
   VIX vs VIX3M rail.
5. **Answer.** Give the data, the date range, and the row count. Label any
   conclusion as the user's or your own analysis of research data.
