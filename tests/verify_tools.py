import asyncio
import json
import logging
import os
import sys

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ToolVerifier")

try:
    from tools.news_analysis import get_news_analysis
    from tools.top_picks_analysis import get_top_picks_analysis
    from tools.winners_dashboard import get_winners_dashboard
except ImportError as e:
    logger.error(f"Failed to import tools: {e}")
    sys.exit(1)


async def verify_tools():
    print("=== Verifying Tools ===")

    # 1. Test get_winners_dashboard (Base)
    print("\n1. Testing get_winners_dashboard...")
    try:
        res = await get_winners_dashboard(limit=3)
        print(f"Success. Result preview: {res[:200]}...")
    except Exception as e:
        print(f"Failed: {e}")

    # 2. Test get_news_analysis (Fixed GCS path)
    print("\n2. Testing get_news_analysis (ABNB)...")
    try:
        res = await get_news_analysis(ticker="ABNB")
        print(f"Success. Result preview: {res[:200]}...")
    except Exception as e:
        print(f"Failed: {e}")

    # 3. Test get_top_picks_analysis (Orchestrator)
    print("\n3. Testing get_top_picks_analysis...")
    try:
        res = await get_top_picks_analysis(limit=2)
        print(f"Success. Result preview: {res[:500]}...")

        # Parse logic check
        data = json.loads(res)
        print(f"Analyzed {data.get('candidates_analyzed')}")
        print(f"Qualified {data.get('candidates_qualified')}")
        if data.get("avoid"):
            print(f"Avoid example: {data['avoid'][0]}")

    except Exception as e:
        print(f"Failed: {e}")


if __name__ == "__main__":
    asyncio.run(verify_tools())
