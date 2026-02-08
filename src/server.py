"""
GammaRips MCP Server
Agent-first options trading intelligence platform
"""

import json
import logging
import os

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

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

# Import authentication middleware (Phase 2)
from auth.middleware import auth_middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

# Import tools
from tools.business_summary import get_business_summary
from tools.customer_service import get_support_policy
from tools.financial_analysis import get_financial_analysis
from tools.fundamental_analysis import get_fundamental_analysis
from tools.fundamental_deep_dive import get_macro_thesis, get_mda_analysis, get_transcript_analysis
from tools.market_events import get_market_events
from tools.market_structure import analyze_market_structure
from tools.news_analysis import get_news_analysis
from tools.performance_tracker import get_performance_summary, get_performance_tracker
from tools.price_data_sql import run_price_query
from tools.stock_analysis import get_stock_analysis
from tools.technical_analysis import get_technical_analysis
from tools.web_search import web_search
from tools.winners_dashboard import get_winners_dashboard

# Register tools with the MCP server
mcp.tool()(get_winners_dashboard)
mcp.tool()(get_stock_analysis)
mcp.tool()(get_macro_thesis)
mcp.tool()(get_mda_analysis)
mcp.tool()(get_transcript_analysis)
mcp.tool()(analyze_market_structure)
mcp.tool()(get_technical_analysis)
mcp.tool()(get_news_analysis)
mcp.tool()(get_business_summary)
mcp.tool()(get_fundamental_analysis)
mcp.tool()(get_financial_analysis)
mcp.tool()(run_price_query)
mcp.tool()(get_market_events)
mcp.tool()(web_search)
mcp.tool()(get_support_policy)
mcp.tool()(get_performance_tracker)
mcp.tool()(get_performance_summary)


def get_tools_list():
    """Return the list of available MCP tools"""
    return [
        {
            "name": "get_winners_dashboard",
            "description": "Get top options signals ranked by conviction. Filter by quality, option type.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max results to return", "default": 10},
                    "min_quality": {"type": "string", "description": "Minimum quality filter (High, Medium, Low)"},
                    "option_type": {"type": "string", "description": "Filter by CALL or PUT"}
                }
            }
        },
        {
            "name": "get_performance_tracker",
            "description": "Track historical signal performance with win rate and P&L.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "Number of days to look back", "default": 30}
                }
            }
        },
        {
            "name": "get_performance_summary",
            "description": "Aggregate stats across all tracked signals.",
            "inputSchema": {"type": "object", "properties": {}}
        },
        {
            "name": "get_stock_analysis",
            "description": "Full analysis for a ticker: fundamentals, technicals, news, financials.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Stock ticker symbol"}
                },
                "required": ["ticker"]
            }
        },
        {
            "name": "get_technical_analysis",
            "description": "Technical analysis: RSI, MACD, patterns, trend analysis.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Stock ticker symbol"}
                },
                "required": ["ticker"]
            }
        },
        {
            "name": "analyze_market_structure",
            "description": "Options flow analysis: vol/OI walls, Greeks scanner.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Stock ticker symbol"}
                },
                "required": ["ticker"]
            }
        },
        {
            "name": "get_macro_thesis",
            "description": "Current market conditions, sector rotation, risk factors.",
            "inputSchema": {"type": "object", "properties": {}}
        },
        {
            "name": "get_market_events",
            "description": "Upcoming earnings, dividends, economic calendar.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "days_ahead": {"type": "integer", "description": "Days to look ahead", "default": 7}
                }
            }
        },
        {
            "name": "get_news_analysis",
            "description": "News sentiment scores and catalysts for a ticker.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Stock ticker symbol"}
                },
                "required": ["ticker"]
            }
        },
        {
            "name": "get_business_summary",
            "description": "Get business profile and summary.",
            "inputSchema": {
                "type": "object",
                "properties": {
                     "ticker": {"type": "string", "description": "Stock ticker symbol"}
                },
                "required": ["ticker"]
            }
        },
        {
            "name": "get_fundamental_analysis",
            "description": "Get fundamental metrics and ratios.",
            "inputSchema": {
                "type": "object",
                "properties": {
                     "ticker": {"type": "string", "description": "Stock ticker symbol"}
                },
                "required": ["ticker"]
            }
        },
        {
            "name": "get_financial_analysis",
            "description": "Get financial health analysis and statements.",
            "inputSchema": {
                "type": "object",
                "properties": {
                     "ticker": {"type": "string", "description": "Stock ticker symbol"}
                },
                "required": ["ticker"]
            }
        },
        {
             "name": "run_price_query",
             "description": "Run custom SQL query on price data.",
             "inputSchema": {
                 "type": "object",
                 "properties": {
                     "query": {"type": "string", "description": "SQL query"}
                 },
                 "required": ["query"]
             }
        },
        {
             "name": "web_search",
             "description": "Search the web for real-time info.",
             "inputSchema": {
                 "type": "object",
                 "properties": {
                     "query": {"type": "string", "description": "Search query"}
                 },
                 "required": ["query"]
             }
        },
        {
             "name": "get_support_policy",
             "description": "Get customer service policy and FAQ.",
             "inputSchema": {
                 "type": "object",
                 "properties": {
                     "query": {"type": "string", "description": "User question"}
                 }
             }
        },
        {
             "name": "get_mda_analysis",
             "description": "Get 10-K/Q MD&A insights.",
             "inputSchema": {
                 "type": "object",
                 "properties": {
                     "ticker": {"type": "string", "description": "Stock ticker symbol"}
                 },
                 "required": ["ticker"]
             }
        },
        {
             "name": "get_transcript_analysis",
             "description": "Get earnings call transcript analysis.",
             "inputSchema": {
                 "type": "object",
                 "properties": {
                     "ticker": {"type": "string", "description": "Stock ticker symbol"}
                 },
                 "required": ["ticker"]
             }
        }
    ]


async def execute_tool(tool_name: str, args: dict, user_info: dict) -> str:
    """Execute a tool by name with provided arguments."""
    tool_map = {
        "get_winners_dashboard": get_winners_dashboard,
        "get_stock_analysis": get_stock_analysis,
        "get_macro_thesis": get_macro_thesis,
        "get_mda_analysis": get_mda_analysis,
        "get_transcript_analysis": get_transcript_analysis,
        "analyze_market_structure": analyze_market_structure,
        "get_technical_analysis": get_technical_analysis,
        "get_news_analysis": get_news_analysis,
        "get_business_summary": get_business_summary,
        "get_fundamental_analysis": get_fundamental_analysis,
        "get_financial_analysis": get_financial_analysis,
        "run_price_query": run_price_query,
        "get_market_events": get_market_events,
        "web_search": web_search,
        "get_support_policy": get_support_policy,
        "get_performance_tracker": get_performance_tracker,
        "get_performance_summary": get_performance_summary,
    }
    
    if tool_name not in tool_map:
        raise ValueError(f"Tool not found: {tool_name}")
        
    func = tool_map[tool_name]
    try:
        # Most tools accept **kwargs
        result = await func(**args)
        return result
    except Exception as e:
        logger.error(f"Error executing {tool_name}: {e}", exc_info=True)
        raise e


async def handle_jsonrpc(request: Request):
    """
    Stateless JSON-RPC endpoint for MCP tool discovery and direct calls.
    Used by Smithery and other MCP clients that don't support SSE transport.
    """
    # Get API key from header
    api_key = request.headers.get("X-API-Key") or request.headers.get("Authorization", "").replace("Bearer ", "")
    
    # Validate API key
    try:
        user_info = await auth_middleware.validate_api_key(api_key)
    except ValueError as e:
        return JSONResponse(
            status_code=401,
            content={
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32001,
                    "message": str(e),
                    "data": {
                        "signup_url": "https://gammarips.com/developers",
                        "docs_url": "https://gammarips.com/developers#quick-start"
                    }
                }
            }
        )
    
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
            result = await execute_tool(tool_name, tool_args, user_info)
            
            # Track usage
            await auth_middleware.track_usage(user_info["user_id"], tool_name)
            
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

    # --- Authentication Middleware ---
    class APIKeyMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            # Skip auth for health checks or public endpoints
            if request.url.path in ["/healthz", "/metrics", "/favicon.ico"]:
                return await call_next(request)
            
            # Skip if auth is disabled via env var
            if not auth_middleware.require_api_key:
                return await call_next(request)

            # Extract API key from headers (X-API-Key or Authorization Bearer) or query param
            api_key = request.headers.get("X-API-Key")
            if not api_key:
                auth_header = request.headers.get("Authorization", "")
                if auth_header.startswith("Bearer "):
                    api_key = auth_header.replace("Bearer ", "")
            
            # Fallback to query param
            if not api_key:
                api_key = request.query_params.get("api_key")
            
            try:
                user = await auth_middleware.validate_api_key(api_key)
                # Store user info in scope for tools to access (if needed)
                request.scope["user"] = user
                
                # Track usage (optional - logic could be more granular per tool)
                # await auth_middleware.track_usage(user["user_id"], "api_access")
                
                response = await call_next(request)
                return response
            except ValueError as e:
                logger.warning(f"Auth failed: {e}")
                return JSONResponse(
                    {
                        "error": str(e),
                        "signup_url": "https://gammarips.com/developers",
                        "docs_url": "https://gammarips.com/developers#quick-start",
                        "support_email": "support@gammarips.com",
                    },
                    status_code=401,
                )
            except Exception as e:
                logger.error(f"Auth error: {e}", exc_info=True)
                return JSONResponse(
                    {
                        "error": "Internal authentication error",
                        "signup_url": "https://gammarips.com/developers",
                        "docs_url": "https://gammarips.com/developers#quick-start",
                        "support_email": "support@gammarips.com",
                    },
                    status_code=500,
                )

    # Add the middleware
    if os.getenv("REQUIRE_API_KEY", "false").lower() == "true":
        app.add_middleware(APIKeyMiddleware)
        logger.info("API Key Middleware added to application pipeline")

    # Add JSON-RPC endpoint (Phase 3: Smithery Support)
    app.add_route("/rpc", handle_jsonrpc, methods=["POST"])
    app.add_route("/jsonrpc", handle_jsonrpc, methods=["POST"])
    logger.info("Added stateless JSON-RPC endpoints")

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
    logger.info(
        f"Authentication: {'Enabled' if os.getenv('REQUIRE_API_KEY', 'false').lower() == 'true' else 'Disabled'}"
    )
    logger.info("========================================")
    logger.info("")
    logger.info("Available tools:")
    logger.info("  1. get_winners_dashboard - Get today's top options signals")
    logger.info("  2. analyze_market_structure - Analyze options flow (Vol/OI Walls)")
    logger.info("  3. get_stock_analysis - Get comprehensive stock analysis (Master Tool)")
    logger.info("  4. get_macro_thesis - Get market context")
    logger.info("  5. get_mda_analysis - Get 10-K/Q insights")
    logger.info("  6. get_transcript_analysis - Get earnings call insights")
    logger.info("  7. get_technical_analysis - Get technical analysis")
    logger.info("  8. get_news_analysis - Get news sentiment analysis")
    logger.info("  9. get_business_summary - Get business profile")
    logger.info("  10. get_fundamental_analysis - Get fundamental metrics")
    logger.info("  11. get_financial_analysis - Get financial health analysis")
    logger.info("  12. run_price_query - Run custom SQL on price data")
    logger.info("  13. get_market_events - Get upcoming calendar events (Earnings, Econ)")
    logger.info("  14. web_search - Search the web for real-time info")
    logger.info("  15. get_support_policy - Get customer service policy/FAQ")
    logger.info("  16. get_performance_tracker - Get signal performance history")
    logger.info("  17. get_performance_summary - Get aggregate performance stats")
    logger.info("")
    logger.info("Starting server...")

    # Run the server with SSE transport
    # Host and port are configured in FastMCP initialization
    port = int(os.getenv("PORT", "8080"))
    logger.info(f"Binding to host: 0.0.0.0 and port: {port}")
    mcp.run(transport="sse")


if __name__ == "__main__":
    main()
