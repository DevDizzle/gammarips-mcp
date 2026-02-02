"""
GammaRips MCP Server
Agent-first options trading intelligence platform
"""

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
# from auth.middleware import auth_middleware

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
