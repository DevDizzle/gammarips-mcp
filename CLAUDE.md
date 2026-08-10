# gammarips-mcp

GammaRips MCP server — options-flow intelligence primitives for AI agents
(curated daily bullish pool, point-in-time features, opportunity surfaces,
bracket labels, regime context). Design rule: **primitives, never a pick** —
no "what should I buy" endpoint. Start with `README.md` for the full tool list.

## Deploy target

- Cloud Run, us-central1, GCP project number `406581297632`
- Primary endpoint: `https://gammarips-mcp-406581297632.us-central1.run.app/mcp` (streamable HTTP); `/sse` is legacy, `/jsonrpc` stateless
- Build/deploy via `cloudbuild.yaml` + `Dockerfile`
- Auth: bearer-token tiering (`gr_live_...` keys), currently shadow rollout — see `SECURITY.md`

## Working here

- Python (`pyproject.toml`); server config in `mcp.json` / `mcp_config.json`
- Docs in `docs/`, run/eval artifacts in `reports/` and `logs/`
- The deployed server is registered as a user-scope MCP (`gammarips-mcp`) in
  Claude Code — trading sessions consume it live; don't break the hosted
  endpoint casually
- Related repos: `../gammarips-mcp-serverjson` (registry/listing fork — keep
  README/tool descriptions in sync when tools change), `../gammarips-trader`
  (primary consumer), `../gammarips-engine` (produces the underlying data)

TODO(Evan): add VERIFIED run/test/deploy commands after next hands-on session.
