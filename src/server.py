"""
GammaRips MCP Server (V3)
Agent-first options-intelligence data vendor: the curated overnight pool,
point-in-time features, realized opportunity/outcome surfaces, and the
methodology playbooks to compose them. Primitives, never a pick.
"""

import inspect
import json
import logging
import os
import time

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from utils.auth import (
    PRICE,
    TRIAL,
    AccessGateMiddleware,
    anon_tools,
    denied_error,
    get_auth_mode,
    resolve_identity,
    tool_allowed,
)
from utils.oauth import (
    PRO_PATH,
    ProEndpointMiddleware,
    authorization_server_metadata,
    oauth_enabled,
    protected_resource_metadata,
)
from utils.oauth import (
    issuer as oauth_issuer,
)
from utils.safety import RateLimitMiddleware, redact

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# 4.1.0 (2026-08-07): the live cohort is now the PAIR (policy label, start date);
# `cohort_start` added to the positions/performance responses; aggregate stats are
# null (never 0.0) at N=0. Minor-bumped so consumers can detect the semantics change.
# 4.2.0 (2026-08-19): OAuth 2.1 resource server. `/pro` = auth-required MCP endpoint
# (401 + RFC 9728 discovery for chat clients), `/mcp` unchanged (anonymous), JWT
# bearers honored everywhere API keys are. No tool or data change.
# 4.3.0 (2026-08-28): connect-time `instructions` in the initialize result
# (/mcp + /jsonrpc): free/pro tiers + signup steps. Playbooks cite V4 tool
# names; start-here gains a "How access works" section. No tool or data change.
SERVER_VERSION = "4.4.0"

# Connect-time guidance, served in the initialize result. This is the
# proactive half of the funnel; the denial envelope in utils.auth is the
# bounce half. PRICE/TRIAL are imported so the same-day price-sync rule
# keeps one code touchpoint. utm_source is distinct from the denial
# envelope's so GA4 can tell connect-time visits from paywall bounces.
_INSTRUCTIONS = (
    "GammaRips serves read-only options-flow data primitives. It never "
    "returns a pick. Your agent reasons to its own contract and exit. "
    "First call get_playbook(name='start-here'). "
    "Free, no credential: get_pool(view='preview'), get_daily_report, "
    "get_playbook, get_regime_context, get_market_calendar_status. "
    f"Pro ({PRICE}, {TRIAL}) unlocks the full pool (enriched / raw / "
    "features views) plus get_signal, get_liquidity, query_outcomes, and "
    "replay_contract. To subscribe: a human starts the trial at "
    "https://gammarips.com/pricing?utm_source=mcp_instructions , then "
    "either signs in through OAuth when adding this server, or creates an "
    "API key at https://gammarips.com/account?utm_source=mcp_instructions "
    "(shown once) and sends it as an 'Authorization: Bearer gr_live_...' "
    "header. If a tool returns subscription_required, relay its message "
    "and next_steps to your human operator. All data is paper-traded "
    "research. Educational only. Not investment advice."
)

# Initialize FastMCP server
mcp = FastMCP(
    name="gammarips",
    instructions=_INSTRUCTIONS,
    host="0.0.0.0",
    port=int(os.getenv("PORT", "8080")),
)

# Import the 9 V4 consolidated tools. Each is a thin arg-driven dispatcher over
# the V3 query logic (see tools/v4.py); the leakage-safe implementations are
# reused verbatim. web_search is KILLED in V4.
from tools.v4 import (
    get_daily_report,
    get_liquidity,
    get_market_calendar_status,
    get_playbook,
    get_pool,
    get_regime_context,
    get_signal,
    query_outcomes,
    replay_contract,
)

# Register tools with the MCP server (9 tools — V4 consolidation, 2026-07-17).
# NOTE: docstrings are the tool descriptions — keep them agent-facing.
_ALL_TOOLS = {
    # the candidate pool (enriched | raw | features | preview)
    "get_pool": get_pool,
    # one ticker/contract (detail | earnings)
    "get_signal": get_signal,
    # fresh entry-day liquidity (one contract | whole pool)
    "get_liquidity": get_liquidity,
    # realized outcomes + receipts substrate (view= modes)
    "query_outcomes": query_outcomes,
    # raw price tape for your own exit rule (minute | day)
    "replay_contract": replay_contract,
    # regime rail (unchanged)
    "get_regime_context": get_regime_context,
    # market calendar (status | scan_dates)
    "get_market_calendar_status": get_market_calendar_status,
    # methodology + field dict + data-contract schema
    "get_playbook": get_playbook,
    # daily report (report | list)
    "get_daily_report": get_daily_report,
}

# Display titles + MCP tool annotations. The claude.ai Connectors Directory
# requires both on every tool, and a human-readable `title` is what a client
# shows instead of the snake_case function name.
#
# This dict is the ONE source of truth: the FastMCP registration below and
# `get_tools_list()` (the stateless JSON-RPC path + server card) both read it,
# so the hosted MCP surface and the card can no longer disagree. Before
# 2026-09-01 only the card carried annotations and the real `tools/list`
# carried none.
#
# All nine tools are read-only queries over a fixed set of backends, so:
# readOnly=True, destructive=False, idempotent=True, openWorld=False.
# `web_search` is the only open-world tool and it is not registered here.
_TOOL_TITLES = {
    "get_pool": "Candidate Pool",
    "get_signal": "Signal Detail",
    "get_liquidity": "Contract Liquidity",
    "query_outcomes": "Realized Outcomes",
    "replay_contract": "Contract Price Replay",
    "get_regime_context": "Market Regime Context",
    "get_market_calendar_status": "Market Calendar Status",
    "get_playbook": "Methodology Playbook",
    "get_daily_report": "Daily Report",
}


def _tool_annotations(name: str) -> ToolAnnotations:
    """Annotations for a registered tool. See _TOOL_TITLES for the rationale."""
    return ToolAnnotations(
        title=_TOOL_TITLES[name],
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )


for _name, _fn in _ALL_TOOLS.items():
    mcp.tool(title=_TOOL_TITLES[_name], annotations=_tool_annotations(_name))(_fn)


# ---------------------------------------------------------------------------
# Prompts — thin orchestrations over the tools. No prompt references a pick.
# ---------------------------------------------------------------------------


@mcp.prompt()
def morning_brief() -> str:
    """Compose a morning briefing from the pool, regime, and surfaces."""
    return (
        "Prepare my GammaRips morning brief. Steps: "
        "1) get_market_calendar_status() — is the market open today? "
        "2) get_regime_context() — does the VIX<=VIX3M rail pass? "
        "3) get_pool() — pull today's curated (enriched) pool. "
        "4) query_outcomes(view='summary', horizon='3d', group_by='delta_bucket') "
        "for historical context. "
        "Then summarize: regime state, the 5 most interesting candidates with "
        "their contract specs and why, and any data caveats (stale OI, "
        "illiquid tail). Do NOT recommend a single trade — present the "
        "surface so I can reason about it."
    )


@mcp.prompt()
def analyze_candidate(ticker: str) -> str:
    """Deep-dive one pool candidate: enrichment, features, history, excursions."""
    return (
        f"Deep-dive the GammaRips candidate {ticker}. Steps: "
        f"1) get_signal(ticker='{ticker}', full=true) for the full enrichment. "
        f"2) query_outcomes(view='surface', ticker='{ticker}', days=60) for its "
        "recent excursion history. "
        f"3) query_outcomes(view='labels', ticker='{ticker}', horizon='3d') for "
        "realized labels. "
        "4) get_playbook(field='<name>') to explain any field you're unsure about. "
        "Synthesize: the thesis, the quantitative profile (delta, momentum, "
        "flow), how similar setups resolved historically, and the honest "
        "risks. No trade recommendation — give me the decision surface."
    )


@mcp.prompt()
def run_your_own_tournament() -> str:
    """Run the bracket-tournament selection pattern over today's pool with MY objective."""
    return (
        "Run the GammaRips tournament selection pattern on today's pool. "
        "First fetch get_playbook(name='run-your-own-tournament') and follow it "
        "exactly: pull get_pool(), shuffle into batches of <=10, "
        "advance top-2 per batch by comparative judgment against MY objective "
        "(ask me for horizon and risk tolerance if I haven't said), repeat to "
        "a winner, run 3 independent brackets, and report the consensus with "
        "confidence (3/3 high, 2/3 medium, else treat as no-selection). Show "
        "your bracket rounds and reasoning."
    )


# ---------------------------------------------------------------------------
# Playbooks as MCP resources
# ---------------------------------------------------------------------------


@mcp.resource("gammarips://playbooks/{name}")
def playbook_resource(name: str) -> str:
    """Methodology playbook (markdown), server-versioned."""
    result = get_playbook(name)
    return result.get("content") or json.dumps(result)


def get_tools_list():
    """Tool metadata for the stateless JSON-RPC endpoint and the server card.

    Generated from the FastMCP registry so descriptions/schemas have exactly
    one source of truth (the tool docstrings) — the old hand-maintained copy
    of this list is where stale-policy drift lived.
    """
    anon = anon_tools()
    tools = []
    for t in mcp._tool_manager.list_tools():
        tools.append(
            {
                "name": t.name,
                "title": _TOOL_TITLES.get(t.name) or t.name,
                "description": t.description,
                "inputSchema": t.parameters,
                "tier": "anon" if t.name in anon else "pro",
                "annotations": _tool_annotations(t.name).model_dump(exclude_none=True)
                if t.name in _TOOL_TITLES
                else {
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "idempotentHint": t.name != "web_search",
                    "openWorldHint": t.name == "web_search",
                },
            }
        )
    return tools


async def execute_tool(tool_name: str, args: dict, user_info: dict = None) -> str:
    """Execute a tool by name with provided arguments."""
    if tool_name not in _ALL_TOOLS:
        raise ValueError(f"Tool not found: {tool_name}")

    func = _ALL_TOOLS[tool_name]
    try:
        # Inject user_info into kwargs for tools that need it
        # We pass it as a hidden argument _user_info
        if user_info:
            args["_user_info"] = user_info

        if inspect.iscoroutinefunction(func):
            result = await func(**args)
        else:
            result = func(**args)

        return result
    except Exception as e:
        logger.error(f"Error executing {tool_name}: {e}", exc_info=True)
        raise e


async def server_card(request: Request):
    """
    Server discovery card for Smithery and other MCP registries.
    https://smithery.ai/docs/build/external#server-scanning
    """
    return JSONResponse(
        {
            "serverInfo": {
                "name": "GammaRips",
                "displayName": "GammaRips Options Intelligence",
                "version": SERVER_VERSION,
                "description": (
                    "Options-flow intelligence primitives for AI agents: a hard-"
                    "curated overnight candidate pool, point-in-time features, "
                    "realized opportunity surfaces (MFE/MAE excursions), bracket "
                    "outcome labels, and methodology playbooks. Your agent reasons "
                    "to its own contract and exit — there is no pick endpoint. "
                    "Paper-traded research data; educational only; not investment "
                    "advice."
                ),
                "homepage": "https://gammarips.com/developers",
                "icon": "https://gammarips.com/logo.png",
            },
            "authentication": {
                # `required` reflects the live rollout mode: true only once
                # REQUIRE_API_KEY is flipped on. Anon tools stay usable without
                # a key regardless; pro tools need one under enforce.
                "required": get_auth_mode() == "enforce",
                "type": "bearer",
                "scheme": "Bearer",
                "description": (
                    "Two ways in. (1) API key: send a GammaRips key (gr_live_...) "
                    "as 'Authorization: Bearer <key>' (or X-API-Key) to /mcp. "
                    "(2) OAuth 2.1: connect a chat client (ChatGPT, Claude, "
                    "Cursor) to /pro and complete the sign-in it offers; the "
                    "access token carries your subscription tier. Free tier tools "
                    "are usable without any credential on /mcp; pro tools require "
                    "an active subscription. https://gammarips.com/pricing"
                ),
                "pricing_url": "https://gammarips.com/pricing",
                "oauth": (
                    {
                        "endpoint": "/pro",
                        "authorization_server": oauth_issuer(),
                        "resource_metadata": "/.well-known/oauth-protected-resource/pro",
                        "grants": [
                            "authorization_code+pkce",
                            "refresh_token",
                            "client_credentials",
                        ],
                    }
                    if oauth_enabled()
                    else None
                ),
            },
            "tools": get_tools_list(),
            "resources": [
                {
                    "uriTemplate": "gammarips://playbooks/{name}",
                    "name": "playbooks",
                    "description": "Methodology playbooks (markdown), server-versioned.",
                }
            ],
            "prompts": [
                {
                    "name": "morning_brief",
                    "description": "Compose a morning briefing from the pool, regime, and surfaces",
                    "arguments": [],
                },
                {
                    "name": "analyze_candidate",
                    "description": "Deep-dive one pool candidate: enrichment, features, history, excursions",
                    "arguments": [
                        {
                            "name": "ticker",
                            "description": "Stock ticker symbol (e.g., NVDA)",
                            "required": True,
                        }
                    ],
                },
                {
                    "name": "run_your_own_tournament",
                    "description": "Run the bracket-tournament selection pattern over today's pool with your objective",
                    "arguments": [],
                },
            ],
        }
    )


async def handle_jsonrpc(request: Request):
    """
    Stateless JSON-RPC endpoint for MCP tool discovery and direct calls.
    Used by Smithery and other MCP clients that don't support streaming
    transports.
    """
    # Parse JSON-RPC request
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            },
        )

    request_id = body.get("id")
    method = body.get("method", "")
    params = body.get("params", {})

    # Handle methods
    if method == "initialize":
        return JSONResponse(
            content={
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "gammarips-mcp", "version": SERVER_VERSION},
                    "instructions": _INSTRUCTIONS,
                },
            }
        )

    elif method == "tools/list":
        # Return list of available tools
        tools = get_tools_list()
        return JSONResponse(
            content={"jsonrpc": "2.0", "id": request_id, "result": {"tools": tools}}
        )

    elif method == "tools/call":
        # Handle tool calls
        tool_name = params.get("name")
        tool_args = params.get("arguments", {})

        # Defense-in-depth: the AccessGateMiddleware already gated this request.
        # Re-check under enforce so a parser divergence between the body-sniff
        # and this handler can't slip a pro tool through. If the middleware
        # didn't resolve an identity (e.g. it missed the tool call), resolve it
        # here rather than falling through ungated — otherwise the guard would
        # fail open in exactly the case it exists for.
        if get_auth_mode() == "enforce":
            identity = getattr(request.state, "identity", None)
            if identity is None:
                identity = resolve_identity(request.headers)
            if not tool_allowed(tool_name, identity.tier, tool_args):
                return JSONResponse(
                    content={
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": denied_error(tool_name),
                    }
                )

        try:
            result = await execute_tool(tool_name, tool_args, None)

            return JSONResponse(
                content={
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(result, default=str)}]
                    },
                }
            )
        except Exception as e:
            return JSONResponse(
                content={
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32603, "message": redact(str(e))},
                }
            )

    else:
        return JSONResponse(
            content={
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }
        )


class RequestLogger(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        duration = time.time() - start

        # Log every request with useful metadata. `endpoint` is "pro" when the
        # /pro gateway rewrote the path to /mcp, so the two surfaces stay
        # distinguishable in the request log.
        logger.info(
            "MCP_REQUEST",
            extra={
                "path": request.url.path,
                "endpoint": request.scope.get("gammarips_endpoint", "mcp"),
                "method": request.method,
                "user_agent": request.headers.get("user-agent", "unknown"),
                "origin": request.headers.get("origin", "unknown"),
                "referer": request.headers.get("referer", "unknown"),
                "duration_ms": round(duration * 1000),
                "status": response.status_code,
            },
        )
        return response


# Expose ASGI app for production servers.
# Streamable HTTP (/mcp) is the primary transport; legacy SSE (/sse +
# /messages) stays mounted for existing consumers during the deprecation
# window; the stateless /rpc endpoints serve registry scanners.
try:
    app = None
    if hasattr(mcp, "streamable_http_app"):
        try:
            app = mcp.streamable_http_app()
            logger.info("Using streamable_http_app() - Streamable HTTP at /mcp (primary)")
            try:
                sse = mcp.sse_app()
                app.router.routes.extend(sse.routes)
                logger.info("Mounted legacy SSE routes (/sse, /messages)")
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Legacy SSE mount failed (continuing HTTP-only): {e}")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"streamable_http_app() failed, falling back to SSE: {e}")
            app = None
    if app is None and hasattr(mcp, "sse_app"):
        logger.info("Using sse_app() - SSE Transport")
        app = mcp.sse_app()
    if app is None:
        logger.warning("No explicit app method found, assuming mcp object is ASGI compatible")
        app = mcp

    # Add middleware. Execution order is outer->inner: CORS, RateLimit,
    # AccessGate, RequestLogger (add order is LIFO — last added is outermost).
    app.add_middleware(RequestLogger)

    # Phase 2 auth + tiering. Runs INSIDE the rate limiter so a bogus-key flood
    # is 429'd before it can trigger a Firestore lookup / cache insert. Modes:
    # off (passthrough) | shadow (log would-be denials, block nothing) |
    # enforce (deny pro tools without a valid key). Env-gated by
    # REQUIRE_API_KEY / AUTH_SHADOW so rollout + rollback are a flag flip.
    app.add_middleware(AccessGateMiddleware)

    # OAuth 2.1 resource server: the /pro gateway. Sits OUTSIDE the access gate
    # (it resolves the credential once and hands it down) and INSIDE the rate
    # limiter (a token flood is 429'd before any signature check). Path-rewrites
    # /pro -> /mcp on success, 401 + RFC 9728 discovery header otherwise.
    app.add_middleware(ProEndpointMiddleware)

    # Per-IP token-bucket rate limiter — defends the paid Google CSE tool
    # and BQ cost surface against unauthenticated abuse. Limits are
    # generous: 60 req/min default, 10 req/min for web_search.
    app.add_middleware(
        RateLimitMiddleware,
        default_per_min=int(os.getenv("RATE_LIMIT_DEFAULT_PER_MIN", "60")),
        web_search_per_min=int(os.getenv("RATE_LIMIT_SEARCH_PER_MIN", "10")),
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Open for maximum distribution
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Fix HTTP 421 errors by Monkey Patching TrustedHostMiddleware to bypass all checks
    try:
        from starlette.middleware.trustedhost import TrustedHostMiddleware

        # Define a permissive call method that bypasses checks
        async def permissive_call(self, scope, receive, send):
            # Bypass host check logic completely and just call the app
            await self.app(scope, receive, send)

        # Apply the monkey patch to the class itself
        TrustedHostMiddleware.__call__ = permissive_call
        logger.info("Monkey-patched TrustedHostMiddleware to bypass all host checks")

    except ImportError:
        logger.warning("Could not import TrustedHostMiddleware for patching, skipping.")
    except Exception as e:
        logger.error(f"Failed to apply TrustedHostMiddleware patch: {e}", exc_info=True)

    # Add JSON-RPC endpoint (stateless; Smithery support)
    app.add_route("/rpc", handle_jsonrpc, methods=["POST"])
    app.add_route("/jsonrpc", handle_jsonrpc, methods=["POST"])

    # Add Server Card (Discovery)
    app.add_route("/.well-known/mcp/server-card.json", server_card, methods=["GET"])
    logger.info("Added stateless JSON-RPC endpoints and server card")

    # OAuth discovery (RFC 9728 protected-resource metadata: root + path forms;
    # RFC 8414 AS metadata mirrored from the issuer for legacy probing).
    app.add_route(
        "/.well-known/oauth-protected-resource", protected_resource_metadata, methods=["GET"]
    )
    app.add_route(
        "/.well-known/oauth-protected-resource/{suffix:path}",
        protected_resource_metadata,
        methods=["GET"],
    )
    app.add_route(
        "/.well-known/oauth-authorization-server", authorization_server_metadata, methods=["GET"]
    )
    logger.info(
        f"OAuth resource server: enabled={oauth_enabled()} issuer={oauth_issuer()} pro={PRO_PATH}"
    )

except Exception as e:
    logger.error(f"Failed to create ASGI app: {e}", exc_info=True)
    # Create dummy app to prevent crash and allow log inspection
    try:
        from starlette.applications import Starlette
        from starlette.responses import JSONResponse
        from starlette.routing import Route

        async def homepage(request):
            return JSONResponse({"error": "MCP App failed to load", "details": str(e)})

        app = Starlette(routes=[Route("/", homepage)])
    except ImportError:
        # If starlette is missing (unlikely given fastmcp deps), just fail
        raise e


def main():
    """Run the MCP server."""
    logger.info("========================================")
    logger.info("GammaRips MCP Server")
    logger.info("========================================")
    logger.info(f"Version: {SERVER_VERSION}")
    logger.info(f"Project ID: {os.getenv('GCP_PROJECT_ID')}")
    logger.info(f"Port: {os.getenv('PORT', '8080')}")
    logger.info(f"Auth mode: {get_auth_mode()}  (off | shadow | enforce)")
    logger.info(f"Anon-tier tools ({len(anon_tools())}): {sorted(anon_tools())}")
    logger.info("========================================")
    logger.info("")
    logger.info(f"Registered tools ({len(_ALL_TOOLS)}):")
    for i, name in enumerate(_ALL_TOOLS, 1):
        logger.info(f"  {i:2d}. {name}")
    logger.info("")
    logger.info("Starting server...")

    port = int(os.getenv("PORT", "8080"))
    logger.info(f"Binding to host: 0.0.0.0 and port: {port}")
    try:
        mcp.run(transport="streamable-http")
    except Exception:  # noqa: BLE001
        logger.warning("streamable-http transport failed, falling back to SSE")
        mcp.run(transport="sse")


if __name__ == "__main__":
    main()
