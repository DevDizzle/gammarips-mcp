# gammarips-mcp

GammaRips MCP server — options-flow intelligence primitives for AI agents
(curated daily bullish pool, point-in-time features, opportunity surfaces,
bracket labels, regime context). Design rule: **primitives, never a pick** —
no "what should I buy" endpoint. Start with `README.md` for the full tool list.

## Deploy target

- Cloud Run, us-central1, GCP project number `406581297632`
- Primary endpoint: `https://mcp.gammarips.com/mcp` (streamable HTTP). That is the branded host every listing, the registry entry and `server.json` point at. The raw `https://gammarips-mcp-406581297632.us-central1.run.app/mcp` still answers but must not be published. `/sse` is legacy, `/jsonrpc` stateless, `/pro` needs a credential.
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

## Deploy — VERIFIED 2026-09-01

```bash
# From anywhere. Use the ABSOLUTE path: the permission allowlist matches on it,
# and `bash scripts/deploy.sh` from inside the repo is denied.
bash /home/user/workspace/projects/gammarips-mcp/scripts/deploy.sh
```

Cloud Run **source deploy** (`gcloud run deploy --source=.`), ~4 min. Facts worth
knowing before you run it:

- **A failed deploy is safe.** Cloud Run keeps the previous revision at 100%
  traffic, so the live server never goes down. Read the failure with
  `gcloud logging read 'resource.labels.revision_name="<failed-rev>"'` — a
  startup crash surfaces as a generic "container failed to listen on PORT=8080",
  and the real cause is one line of Python traceback in those logs.
- **`deploy.sh` env must match live before you run it.** `--set-env-vars`
  REPLACES the set, so a stale script silently rolls back console-set policy.
  Diff it against `gcloud run services describe gammarips-mcp` first.
- **`mcp` must stay pinned `>=1.25.0,<2`.** mcp 2.x renamed FastMCP to MCPServer
  and dropped `mcp.server.fastmcp`, which this server imports.
- After a version change, sync `../gammarips-mcp-serverjson` (`server.json` +
  `.cursor-plugin/plugin.json`), run `python scripts/validate_listing.py --live`
  there, and re-publish the registry with its `publish-registry.yml` workflow.

Verify a deploy by calling the live server, not by reading the revision name:
`initialize` then `tools/list` against `https://mcp.gammarips.com/mcp` should
return 9 tools, each with a `title` and `annotations.readOnlyHint`.
