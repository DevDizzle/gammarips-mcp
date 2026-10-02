# GammaRips for Claude

Better-quality option contracts every trading night, and the history to plan
the exit. Claude builds the trade plan with you.

Every US trading night, GammaRips ranks about 3,500 optionable US stocks by
liquidity, keeps the 100 most liquid, keeps the bullish names, and selects one
out-of-the-money call in each on contract liquidity. The result is a pool of
roughly 40 to 50 contracts with deep books:

- Median open interest 4,664 and median session volume 1,039, against 893 and
  233 before the liquidity rule (pool contracts since 2026-08-24).
- The thinnest 10% still carry 1,635 open interest, against 86 before.
- In a 60-day study, no-fill at the 10:00 ET entry fell from 40.5% to 6.1%.

Each contract comes with a thesis, technicals, a catalyst, and point-in-time
features. GammaRips also serves what past pool contracts did: how far each one
moved for and against (the opportunity surface), how often it touched each
profit level, and a score for any target and stop you choose. You set the exit
from history instead of a guess.

## What is in the plugin

- **MCP server:** `https://mcp.gammarips.com/pro`, 9 read-only tools.
- **Skills:**
  - `gammarips-trade-plan`: ask for a trade and get 1 to 3 candidates that
    pass the liquidity and earnings checks, each with entry, target, stop,
    maximum loss, and size, or a reasoned no-trade.
  - `gammarips-morning-brief`: market status, pool freshness, the daily
    report, the VIX regime rail, and a pool snapshot.
  - `gammarips-exit-lab`: test a target, stop, or trailing stop against the
    history of past pool contracts.
  - `gammarips-options-flow`: how to use the data, and the rules for every
    answer.

## Sign-in and plans

When you connect, Claude opens the GammaRips sign-in page (OAuth 2.1). A free
GammaRips account gets the preview pool, the daily report, regime, market
calendar, and methodology tools. Trade plans, the full pool, signal detail,
liquidity, outcomes, and replay need GammaRips Pro. Plans and the free trial:
[gammarips.com/pricing](https://gammarips.com/pricing).

## What the plugin sends and runs

- The plugin runs no local commands, scripts, or hooks.
- Claude sends each tool call (the tool name and its arguments, such as a
  ticker or a date) to `mcp.gammarips.com` with your OAuth access token.
  GammaRips never receives your conversation.
- GammaRips logs request metadata (IP address, user agent, path, time) for 30
  days and keeps a usage record of each tool call (tool name, account ID,
  plan, time, no arguments). See the
  [privacy policy](https://gammarips.com/privacy).

## Support

Email evan@gammarips.com or use
[gammarips.com/about#contact](https://gammarips.com/about#contact).

GammaRips has no pick endpoint: the plan is Claude's analysis with you, and
you decide. GammaRips never places trades. Paper-traded research data.
Educational only. Not investment advice.
