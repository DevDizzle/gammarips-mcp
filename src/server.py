"""
GammaRips MCP Server
Agent-first options trading intelligence platform
"""

import json
import logging
import os
import time
import inspect

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Initialize FastMCP server
mcp = FastMCP(name="gammarips", host="0.0.0.0", port=int(os.getenv("PORT", "8080")))

# Import tools
from tools.overnight_signals import (
    get_overnight_signals,
    get_enriched_signals,
    get_signal_detail,
    get_todays_pick,
    get_freemium_preview,
)
from tools.performance_tracker import (
    get_signal_performance,
    get_win_rate_summary,
    get_open_position,
    get_position_history,
)
from tools.reports import get_daily_report, get_report_list
from tools.metadata import get_available_dates, get_enriched_signal_schema
from tools.web_search import web_search

# Register tools with the MCP server
mcp.tool()(get_overnight_signals)
mcp.tool()(get_enriched_signals)
mcp.tool()(get_signal_detail)
mcp.tool()(get_todays_pick)
mcp.tool()(get_freemium_preview)
mcp.tool()(get_signal_performance)
mcp.tool()(get_win_rate_summary)
mcp.tool()(get_open_position)
mcp.tool()(get_position_history)
mcp.tool()(get_daily_report)
mcp.tool()(get_report_list)
mcp.tool()(get_available_dates)
mcp.tool()(get_enriched_signal_schema)
mcp.tool()(web_search)


def get_tools_list():
    """Return the list of available MCP tools"""
    return [
        {
            "name": "get_overnight_signals",
            "description": "Returns raw overnight scanner signals for a given date. Use this to find tickers where smart money moved overnight.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "scan_date": {
                        "type": "string",
                        "description": "Filter by date (YYYY-MM-DD). Defaults to most recent scan date."
                    },
                    "direction": {
                        "type": "string",
                        "enum": ["bull", "bear"],
                        "description": "Filter by direction"
                    },
                    "min_score": {
                        "type": "integer",
                        "description": "Minimum conviction score (1-10)"
                    },
                    "ticker": {
                        "type": "string",
                        "description": "Filter by specific ticker symbol"
                    },
                    "limit": {
                        "type": "integer",
                        "default": 50,
                        "description": "Max results to return"
                    }
                }
            },
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False
            }
        },
        {
            "name": "get_enriched_signals",
            "description": "Returns AI-enriched overnight signals for a scan_date (news, technicals, catalyst, recommended contract). V5.3 enrichment gate is `overnight_score >= 1`, spread <= 10%, directional UOA > $500K. This tool returns all rows cleared by that gate — the single daily tradeable pick comes from `get_todays_pick`.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "scan_date": {
                        "type": "string",
                        "description": "Filter by date (YYYY-MM-DD). Defaults to most recent scan date."
                    },
                    "direction": {
                        "type": "string",
                        "enum": ["bull", "bear"],
                        "description": "Filter by direction"
                    },
                    "ticker": {
                        "type": "string",
                        "description": "Filter by specific ticker symbol"
                    },
                    "limit": {
                        "type": "integer",
                        "default": 25,
                        "description": "Max results to return"
                    }
                }
            },
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False
            }
        },
        {
            "name": "get_signal_detail",
            "description": "Deep dive on a single ticker's overnight signal. Returns full enriched signal data including recommended contract.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "The ticker symbol"
                    },
                    "scan_date": {
                        "type": "string",
                        "description": "Filter by date (YYYY-MM-DD). Defaults to most recent."
                    }
                },
                "required": ["ticker"]
            },
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False
            }
        },
        {
            "name": "get_signal_performance",
            "description": "Track how signals actually performed against market outcomes.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "scan_date": {
                        "type": "string",
                        "description": "Filter by date (YYYY-MM-DD)"
                    },
                    "ticker": {
                        "type": "string",
                        "description": "Filter to specific ticker"
                    },
                    "direction": {
                        "type": "string",
                        "enum": ["bull", "bear"],
                        "description": "Filter by direction"
                    },
                    "outcome": {
                        "type": "string",
                        "enum": ["win", "loss"],
                        "description": "Filter by outcome"
                    },
                    "limit": {
                        "type": "integer",
                        "default": 50,
                        "description": "Max results"
                    }
                }
            },
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False
            }
        },
        {
            "name": "get_win_rate_summary",
            "description": "Aggregate performance statistics (win rate, average return).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "default": 30,
                        "description": "Lookback period in days"
                    }
                }
            },
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False
            }
        },
        {
            "name": "get_daily_report",
            "description": "Returns the full daily intelligence report (markdown content).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "Filter by date (YYYY-MM-DD). Defaults to most recent."
                    }
                }
            },
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False
            }
        },
        {
            "name": "get_report_list",
            "description": "List available reports.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "default": 10,
                        "description": "Number of reports to return"
                    }
                }
            },
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False
            }
        },
        {
            "name": "get_available_dates",
            "description": "Returns which scan dates have data available.",
            "inputSchema": {
                "type": "object",
                "properties": {}
            },
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False
            }
        },
        {
            "name": "get_todays_pick",
            "description": "Returns GammaRips' canonical daily V5.3 pick from Firestore todays_pick/{scan_date}. This is the single source of truth for 'what did GammaRips pick today' — do NOT re-filter. Returns {has_pick, ticker, direction, recommended_contract, recommended_strike, vol_oi_ratio, moneyness_pct, vix3m_at_enrich, effective_at, policy_version, skip_reason?}. When has_pick=false, skip_reason explains why (no_candidates_passed_gates | regime_fail_closed | vix_backwardation).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "scan_date": {
                        "type": "string",
                        "description": "Filter by date (YYYY-MM-DD). Defaults to most recent."
                    }
                }
            },
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False
            }
        },
        {
            "name": "get_freemium_preview",
            "description": "Top N enriched signals for the most recent scan with minimal fields (ticker, direction, score, directional UOA, headline). For public/freemium teasers; chat agents should use get_signal_detail for contract/thesis depth.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "default": 5,
                        "description": "Number of preview rows (clamped 1-20)"
                    }
                }
            },
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False
            }
        },
        {
            "name": "get_open_position",
            "description": "Returns currently-open V5.3 paper positions from forward_paper_ledger with live Polygon option prices and unrealized P&L. Use this to answer 'am I in a trade right now?' and 'what's it worth?' questions. Returns a list — possibly empty if no position is open. Fields: ticker, direction, recommended_contract, entry_price, target_price, stop_price, current_mid, unrealized_return_pct, days_since_entry, scan_date.",
            "inputSchema": {
                "type": "object",
                "properties": {}
            },
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": True
            }
        },
        {
            "name": "get_position_history",
            "description": "Returns realized (closed) V5.3 paper trades from the last N days, row-level, for chat-agent answers like 'show me recent wins/losses'. PIT-safe: only rows where exit_timestamp IS NOT NULL and DATE(exit_timestamp) < today.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "default": 30,
                        "description": "Lookback window in days"
                    },
                    "limit": {
                        "type": "integer",
                        "default": 50,
                        "description": "Max rows (clamped 1-200)"
                    }
                }
            },
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False
            }
        },
        {
            "name": "get_enriched_signal_schema",
            "description": "Returns the BigQuery column schema of overnight_signals_enriched. Chat agents use this to introspect available fields before asking 'why this pick?' without hallucinating field names.",
            "inputSchema": {
                "type": "object",
                "properties": {}
            },
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False
            }
        },
        {
            "name": "web_search",
            "description": "Search the web for real-time info or to verify facts.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query"
                    },
                    "num_results": {
                        "type": "integer",
                        "default": 5,
                        "description": "Number of results to return"
                    }
                },
                "required": ["query"]
            },
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": False,
                "openWorldHint": True
            }
        }
    ]


async def execute_tool(tool_name: str, args: dict, user_info: dict = None) -> str:
    """Execute a tool by name with provided arguments."""
    tool_map = {
        "get_overnight_signals": get_overnight_signals,
        "get_enriched_signals": get_enriched_signals,
        "get_signal_detail": get_signal_detail,
        "get_todays_pick": get_todays_pick,
        "get_freemium_preview": get_freemium_preview,
        "get_signal_performance": get_signal_performance,
        "get_win_rate_summary": get_win_rate_summary,
        "get_open_position": get_open_position,
        "get_position_history": get_position_history,
        "get_daily_report": get_daily_report,
        "get_report_list": get_report_list,
        "get_available_dates": get_available_dates,
        "get_enriched_signal_schema": get_enriched_signal_schema,
        "web_search": web_search,
    }
    
    if tool_name not in tool_map:
        raise ValueError(f"Tool not found: {tool_name}")
        
    func = tool_map[tool_name]
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
    return JSONResponse({
        "serverInfo": {
            "name": "GammaRips",
            "displayName": "GammaRips Options Intelligence",
            "version": "1.0.0",
            "description": "AI-powered options trading signals. Get high-conviction setups backed by fundamentals, technicals, and options flow analysis. 64% win rate across 200+ tracked signals.",
            "homepage": "https://gammarips.com/developers",
            "icon": "https://gammarips.com/logo.png"
        },
        "authentication": {
            "required": False
        },
        "tools": get_tools_list(),
        "resources": [],
        "prompts": [
            {
                "name": "get_todays_signals",
                "description": "Get today's high-conviction options trading signals",
                "arguments": [
                    {
                        "name": "direction",
                        "description": "Optional: 'bull' or 'bear'",
                        "required": False
                    }
                ]
            },
            {
                "name": "analyze_ticker_signal",
                "description": "Get deep dive analysis for a specific ticker's signal",
                "arguments": [
                    {
                        "name": "ticker",
                        "description": "Stock ticker symbol (e.g., NVDA)",
                        "required": True
                    }
                ]
            },
            {
                "name": "check_performance",
                "description": "Check the win rate and performance of recent signals",
                "arguments": []
            }
        ]
    })


async def handle_jsonrpc(request: Request):
    """
    Stateless JSON-RPC endpoint for MCP tool discovery and direct calls.
    Used by Smithery and other MCP clients that don't support SSE transport.
    """
    # No auth check needed
    
    # Parse JSON-RPC request
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"}
            }
        )
    
    request_id = body.get("id")
    method = body.get("method", "")
    params = body.get("params", {})
    
    # Handle methods
    if method == "initialize":
        return JSONResponse(content={
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "gammarips-mcp",
                    "version": "1.0.0"
                }
            }
        })
    
    elif method == "tools/list":
        # Return list of available tools
        tools = get_tools_list()
        return JSONResponse(content={
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"tools": tools}
        })
    
    elif method == "tools/call":
        # Handle tool calls
        tool_name = params.get("name")
        tool_args = params.get("arguments", {})
        
        try:
            result = await execute_tool(tool_name, tool_args, None)
            
            return JSONResponse(content={
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}
            })
        except Exception as e:
            return JSONResponse(content={
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32603, "message": str(e)}
            })
    
    else:
        return JSONResponse(content={
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"}
        })


class RequestLogger(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        duration = time.time() - start
        
        # Log every request with useful metadata
        logger.info(
            "MCP_REQUEST",
            extra={
                "path": request.url.path,
                "method": request.method,
                "user_agent": request.headers.get("user-agent", "unknown"),
                "origin": request.headers.get("origin", "unknown"),
                "referer": request.headers.get("referer", "unknown"),
                "duration_ms": round(duration * 1000),
                "status": response.status_code,
            }
        )
        return response


# Expose ASGI app for production servers
try:
    if hasattr(mcp, "sse_app"):
        logger.info("Using sse_app() - SSE Transport")
        app = mcp.sse_app()
    elif hasattr(mcp, "http_app"):
        logger.info("Using http_app() - HTTP Transport")
        app = mcp.http_app()
    elif hasattr(mcp, "_http_app"):
        logger.info("Using _http_app")
        app = mcp._http_app
    else:
        logger.warning("No explicit app method found, assuming mcp object is ASGI compatible")
        app = mcp

    # Add middleware
    app.add_middleware(RequestLogger)
    
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

    # Add JSON-RPC endpoint (Phase 3: Smithery Support)
    app.add_route("/rpc", handle_jsonrpc, methods=["POST"])
    app.add_route("/jsonrpc", handle_jsonrpc, methods=["POST"])
    
    # Add Server Card (Discovery)
    app.add_route("/.well-known/mcp/server-card.json", server_card, methods=["GET"])
    logger.info("Added stateless JSON-RPC endpoints and server card")

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
    logger.info("Version: 1.0.0")
    logger.info(f"Project ID: {os.getenv('GCP_PROJECT_ID')}")
    logger.info(f"Port: {os.getenv('PORT', '8080')}")
    logger.info("Authentication: Disabled")
    logger.info("========================================")
    logger.info("")
    logger.info("Available tools:")
    logger.info("   1. get_overnight_signals")
    logger.info("   2. get_enriched_signals")
    logger.info("   3. get_signal_detail")
    logger.info("   4. get_todays_pick        (V5.3 canonical pick)")
    logger.info("   5. get_freemium_preview   (V5.3 top-N teaser)")
    logger.info("   6. get_signal_performance")
    logger.info("   7. get_win_rate_summary")
    logger.info("   8. get_open_position      (V5.3 live position + Polygon mid)")
    logger.info("   9. get_position_history   (V5.3 realized ledger)")
    logger.info("  10. get_daily_report")
    logger.info("  11. get_report_list")
    logger.info("  12. get_available_dates")
    logger.info("  13. get_enriched_signal_schema")
    logger.info("  14. web_search")
    logger.info("")
    logger.info("Starting server...")

    # Run the server with SSE transport
    # Host and port are configured in FastMCP initialization
    port = int(os.getenv("PORT", "8080"))
    logger.info(f"Binding to host: 0.0.0.0 and port: {port}")
    mcp.run(transport="sse")


if __name__ == "__main__":
    main()