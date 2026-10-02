---
name: gammarips-morning-brief
description: Build a morning brief from GammaRips data - market calendar, pool freshness, the daily report, the VIX regime rail, and a snapshot of the nightly options-flow pool. Use when the user asks for a morning brief, a pre-market read, what is on the board today, or what GammaRips shows today. Presents data only and never picks a trade.
---

# GammaRips morning brief

Build one short brief from live GammaRips data. Run the steps in order. If a
step fails, say which one and continue with the rest.

## Steps

1. **Market status.** Call `get_market_calendar_status()`. If the market is
   closed today, say so and give the next open. Continue: the latest report and
   pool are still useful.
2. **Freshness.** Call `get_market_calendar_status(view="freshness")`. Record
   `pool_scan_date`, `pool_rows`, and `fresh`. If `fresh` is false, give the
   `reasons` and say which scan date the pool is from. Before about 06:00 ET
   the new pool does not exist yet, so a stale result at that time is normal.
3. **Daily report.** Call `get_daily_report()`. Take the title, the scan date,
   and three to five themes.
4. **Regime.** Call `get_regime_context()`. Give VIX, VIX3M, and whether the
   rail passes (it passes when VIX is at or below VIX3M). Say that the regime
   lags the live pool by one to two trading days, and give its scan date.
5. **Pool snapshot.** Call `get_pool(view="enriched")`. If it returns
   `subscription_required`, give the user the tool's message as it is written,
   one time, then call `get_pool(view="preview")` and use that.

## Output

Use this order and keep it short:

- **Header:** today's date, market status, pool scan date, row count, fresh or
  not.
- **Regime:** one line.
- **Report themes:** three to five bullets.
- **Pool snapshot:** up to 10 names in a table. With the enriched view, show
  ticker, contract (strike and expiration), delta, days to expiration, and a
  one-line thesis. With the preview view, show ticker, score, and headline.
  Keep the order the tool returns, and say that the order is not a ranking of
  trades.
- **Caveats:** paper-traded research data, educational only, not investment
  advice. Add any freshness reason from step 2.
- **Next questions:** offer a deep dive on one ticker (`get_signal`), a
  liquidity check on one contract (`get_liquidity`), or an exit test (the
  `gammarips-exit-lab` skill).

## Rules

- Never choose a contract for the user, and never say what GammaRips would buy.
  If the user asks "which one?", give the data for the names they ask about and
  say that the choice is theirs.
- Never state or suggest an expected return or a win rate.
- Do not add news or prices from outside these tools without saying where they
  came from.
