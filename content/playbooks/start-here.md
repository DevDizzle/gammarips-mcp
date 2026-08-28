# Start Here — What This Server Is (and Deliberately Isn't)

GammaRips is an overnight options-flow data engine. Every trading night it ranks 3,532 optionable US names by liquidity, takes the top 100, keeps the bullish ones, and prices one out-of-the-money call in each. That is a pool of roughly 40 to 50 contracts. This MCP server gives your agent that pool, the point-in-time features behind it, and the realized outcome/opportunity history to reason against.

**The pool is not a list of the best contracts, and we do not claim it is.** Two pre-registered studies on 2026-08-22 found it indistinguishable from matched random optionable contracts on the same tape. What the liquidity rule measurably fixes is executability: on a 60-day window ending 2026-08-14, no-fill at 10:00 ET went from 40.5% to 6.1%. Those are study numbers, not a live property of today's pool. The full null results are in `get_playbook("selection-research-closed")`. Read it before you build anything on the pool.

**What you get:**
- **The curated pool** — today's enriched candidates with narrative context (`get_pool(view="enriched")`, `get_signal(ticker=...)`) and historical point-in-time feature vectors (`get_pool(view="features")`).
- **The opportunity surface** — for every pool contract, the realized max-favorable / max-adverse excursion of the option premium over a 3-trading-day window with NO exit applied (`query_outcomes(view="surface")`). Profit *potential*, with the exit left as a free variable.
- **Realized labels** — how every pool contract resolved under two reference brackets: the live same-day GIGO bracket and a 3-day companion (`query_outcomes(view="labels")`, `query_outcomes(view="summary")`).
- **Exit exploration** — score *your* bracket against the surface (`query_outcomes(view="exit_rule")`).
- **Regime + safety context** — `get_regime_context`, `get_market_calendar_status`.
- **Receipts** — the engine's own paper-traded track record, realized rows only (`query_outcomes(view="positions")`, `query_outcomes(view="performance")`). The live cohort was RESET on 2026-08-25 when the liquid-universe funnel went live, so expect near-zero N for now: `total_trades: 0` with `null` aggregates means "not accrued yet", not a 0% win rate. See `get_playbook("changelog")`.
- **Methodology** — these playbooks, versioned server-side.

**What this server will never do:**
- **Return a pick.** There is no "what should I buy today" endpoint, by design. Every subscriber's agent reasons from the same primitives to its *own* contract and its *own* exit. That keeps flow diffuse (nobody stampedes one thin contract) and keeps this a data product, not investment advice.
- **Sell you a return.** The whole pool traded under any one fixed exit is *negative* on average — we publish that openly (`query_outcomes(view="summary")`). The value is the excursion structure inside the pool: contracts routinely trade through large favorable excursions before resolving. How much of that your agent captures is a function of *its* selection and *its* exit discipline.

**How access works (free vs Pro):**
- Free, no credential: `get_pool(view="preview")`, `get_daily_report`, `get_playbook`, `get_regime_context`, `get_market_calendar_status`.
- Pro unlocks the full pool (`view="enriched"` / `"raw"` / `"features"`) plus `get_signal`, `get_liquidity`, `query_outcomes`, and `replay_contract`.
- To subscribe, a human starts the trial at https://gammarips.com/pricing?utm_source=mcp_playbook . Then either sign in with OAuth when adding this server (Claude, ChatGPT, Cursor — Pro applies on the next token refresh or on reconnect), or create an API key at https://gammarips.com/account (the key is shown once) and send it as an `Authorization: Bearer gr_live_...` header.
- If a Pro tool returns `subscription_required`, relay its `message` and `next_steps` to your human operator. Setup docs: https://gammarips.com/developers .

**Where to go next:**
1. `get_playbook("daily-workflow")` — the morning pattern.
2. `get_playbook("run-your-own-tournament")` — a selection pattern you can run with your own model.
3. `get_playbook("exit-lab")` — exploring the exit space honestly.
4. `get_playbook("leakage-and-data-contract")` — what every column means and when it was knowable. Read this before doing any research.
5. `get_playbook("methodology")` — the claim-tagged methodology + findings corpus: how the pool is built and why, and what's proven / falsified / fragile on our cohorts. Cite these notes by name (each is fetchable with `get_playbook(name="<slug>")`).

*All data is paper-traded research output. Educational only. Not investment advice.*
