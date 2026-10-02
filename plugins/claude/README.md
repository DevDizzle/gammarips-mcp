# GammaRips for Claude

Read-only US options-flow data for Claude, plus three skills that use it.

Every US trading night, GammaRips ranks about 3,500 optionable US stocks by
liquidity, keeps the 100 most liquid, keeps the bullish names, and prices one
out-of-the-money call in each. The result is a pool of roughly 40 to 50
contracts with point-in-time features, a short thesis, technicals, and flow
context. GammaRips also serves what those contracts did afterwards: how far
each one moved for and against (the opportunity surface), touch
probabilities, and bracket outcome labels.

There is no pick. GammaRips never tells you what to buy. Claude reasons over
the data and the conclusion is yours. We publish the uncomfortable numbers
too: two pre-registered studies found the pool indistinguishable from matched
random optionable contracts, and the whole pool traded under any one fixed
exit has a negative historical average.

## What is in the plugin

- **MCP server:** `https://mcp.gammarips.com/pro`, 9 read-only tools.
- **Skills:**
  - `gammarips-options-flow`: how to use the data honestly (no pick, no
    promised returns, point-in-time rules).
  - `gammarips-morning-brief`: market status, pool freshness, the daily
    report, the VIX regime rail, and a pool snapshot.
  - `gammarips-exit-lab`: test a target, stop, or trailing stop against the
    realized history of pool contracts.

## Sign-in and plans

When you connect, Claude opens the GammaRips sign-in page (OAuth 2.1). A free
GammaRips account gets the preview pool, the daily report, regime, market
calendar, and methodology tools. The full pool, signal detail, liquidity,
outcome, and replay tools need GammaRips Pro. Plans:
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

Paper-traded research data. Educational only. Not investment advice.
GammaRips never places trades.
