# Start Here — What This Server Is (and Deliberately Isn't)

GammaRips is an overnight options-flow intelligence engine. Every trading morning it scans the US options market for unusual institutional activity and curates it *hard* — from thousands of names down to a small high-signal BULLISH pool (~50 candidates). This MCP server gives your agent that pool, the point-in-time features behind it, and the realized outcome/opportunity history to reason against.

**What you get:**
- **The curated pool** — today's enriched candidates with narrative context (`get_enriched_signals`, `get_signal_detail`) and historical point-in-time feature vectors (`get_pool_features`).
- **The opportunity surface** — for every pool contract, the realized max-favorable / max-adverse excursion of the option premium over a 3-trading-day window with NO exit applied (`get_opportunity_surface`). Profit *potential*, with the exit left as a free variable.
- **Realized labels** — how every pool contract resolved under two reference brackets: the live same-day GIGO bracket and a 3-day companion (`query_outcomes`, `get_outcome_summary`).
- **Exit exploration** — score *your* bracket against the surface (`estimate_exit_rule`).
- **Regime + safety context** — `get_regime_context`, `get_market_calendar_status`.
- **Receipts** — the engine's own paper-traded track record, realized rows only (`get_position_history`, `get_historical_performance`).
- **Methodology** — these playbooks, versioned server-side.

**What this server will never do:**
- **Return a pick.** There is no "what should I buy today" endpoint, by design. Every subscriber's agent reasons from the same primitives to its *own* contract and its *own* exit. That keeps flow diffuse (nobody stampedes one thin contract) and keeps this a data product, not investment advice.
- **Sell you a return.** The whole pool traded under any one fixed exit is *negative* on average — we publish that openly (`get_outcome_summary`). The value is the excursion structure inside the pool: contracts routinely trade through large favorable excursions before resolving. How much of that your agent captures is a function of *its* selection and *its* exit discipline.

**Where to go next:**
1. `get_playbook("daily-workflow")` — the morning pattern.
2. `get_playbook("run-your-own-tournament")` — a selection pattern you can run with your own model.
3. `get_playbook("exit-lab")` — exploring the exit space honestly.
4. `get_playbook("leakage-and-data-contract")` — what every column means and when it was knowable. Read this before doing any research.
5. `get_playbook("methodology")` — the claim-tagged methodology + findings corpus: how the pool is built and why, and what's proven / falsified / fragile on our cohorts. Cite these notes by name (each is fetchable with `get_playbook(name="<slug>")`).

*All data is paper-traded research output. Educational only. Not investment advice.*
