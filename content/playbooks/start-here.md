# Start Here: Build a Trade Plan from the GammaRips Pool

GammaRips gives your agent a ready, high-quality options universe every trading night, plus the history to plan the exit. Each night the engine ranks about 3,500 optionable US stocks, keeps the 100 most liquid, keeps the bullish names, and selects one out-of-the-money call in each **on contract liquidity**. The result is a pool of roughly 40 to 50 contracts with deep books:

- Median open interest **4,664** contracts and median session volume **1,039**, against 906 and 232 in the 60 scan days before the liquidity rule (pool contracts since 2026-08-24).
- The thinnest 10% of the pool still carries 1,635 open interest, against 29 before.
- In a 60-day study, no-fill at the 10:00 ET entry fell from **40.5% to 6.1%** when the engine moved to this rule.

Liquid contracts are the ones you can enter and exit near the quote. A thin contract costs you on the way in and again on the way out.

## Your job: help the user build their own trade plan

When the user asks for a trade ("find me a good options trade", "what should I look at today"), build a plan with them. Do not answer with pool-wide averages. Use this order:

1. **Is there a session and a fresh pool?** `get_market_calendar_status()` and `get_market_calendar_status(view="freshness")`. If the market is closed, plan for the next session from the latest pool.
2. **Is the regime OK?** `get_regime_context()`. The rail passes when VIX is at or below VIX3M.
3. **Read the pool.** `get_pool(view="enriched")` gives each name with its thesis, technicals, catalyst, and selected contract.
4. **Shortlist 1 to 3 candidates.** Use the user's own criteria. If the user has none, start with |delta| 0.20 to 0.46, the engine's reference band (`get_playbook("delta-band-0-20-0-46")`). For each one, check earnings before expiration with `get_signal(ticker=..., view="earnings")` and fresh liquidity with `get_liquidity(contract=...)`. Drop any name that fails.
5. **Plan the exit from history.** `query_outcomes(view="harvest", targets=[...], stops=[...])` gives how often past pool contracts touched each profit level and each stop. `query_outcomes(view="surface", aggregate_only=True)` gives their typical favorable and adverse moves. Set the target and the stop from those numbers. `query_outcomes(view="exit_rule", target_pct=..., stop_pct=...)` scores the bracket.
6. **Give the plan.** For each candidate: the contract, why it passed, entry (about 10:00 ET with a limit order near the mid), target, stop, maximum loss, and a size that keeps the maximum loss inside the user's risk budget. If nothing passes, give a reasoned no-trade with the exact check that failed.

Label the result as your analysis of GammaRips data. The user decides. Not investment advice.

## What you get

- **The curated pool:** `get_pool(view="enriched")`, `get_signal(ticker=...)`, and point-in-time feature vectors with `get_pool(view="features")`.
- **Liquidity checks:** `get_liquidity` for fresh open interest and session volume on one contract or the whole pool.
- **The opportunity surface:** for every past pool contract, how far the option premium moved in its favor and against over 3 trading days, with no exit applied (`query_outcomes(view="surface")`).
- **The exit lab:** touch probabilities (`view="harvest"`), reference brackets (`view="labels"`, `view="summary"`), and a score for any bracket or trailing stop (`view="exit_rule"`). `replay_contract` returns the minute or daily price tape.
- **Context:** `get_regime_context`, `get_market_calendar_status`, and the written `get_daily_report`.
- **Methodology:** these playbooks, versioned server-side.

## Rules for your answers

- GammaRips has no pick endpoint. Your agent builds the plan, so subscribers do not all crowd into one contract.
- Do not state an expected return or a win rate, and do not claim the pool returns more than other contracts. Quality claims are about execution: liquidity, open interest, volume, and fills.
- Pool-wide averages describe every contract under one fixed rule. They are not a forecast for the plan you build. Quote them only when the user asks about the whole pool.
- `query_outcomes(view="positions")` and `view="performance"` hold the history of a retired engine test (one pick a day under one fixed exit, retired 2026-09-28). It is not the product. Do not use it to judge the pool.

## How access works (free vs Pro)

- Free, no credential: `get_pool(view="preview")`, `get_daily_report`, `get_playbook`, `get_regime_context`, `get_market_calendar_status`.
- Pro unlocks the full pool (`view="enriched"` / `"raw"` / `"features"`) plus `get_signal`, `get_liquidity`, `query_outcomes`, and `replay_contract`. The trade plan above needs Pro.
- To subscribe, a human starts the trial at https://gammarips.com/pricing?utm_source=mcp_playbook . Then either sign in with OAuth when adding this server (Claude, ChatGPT, Cursor: Pro applies on the next token refresh or on reconnect), or create an API key at https://gammarips.com/account (the key is shown once) and send it as an `Authorization: Bearer gr_live_...` header.
- If a Pro tool returns `subscription_required`, relay its `message` and `next_steps` to your human operator. Setup docs: https://gammarips.com/developers .

## Where to go next

1. `get_playbook("exit-lab")`: how to set targets and stops from the surface.
2. `get_playbook("daily-workflow")`: the morning pattern.
3. `get_playbook("run-your-own-tournament")`: a selection pattern you can run with your own model.
4. `get_playbook("leakage-and-data-contract")`: what every column means and when it was knowable.
5. `get_playbook("methodology")`: how the pool is built and the full research record.

*All data is paper-traded research output. Educational only. Not investment advice.*
