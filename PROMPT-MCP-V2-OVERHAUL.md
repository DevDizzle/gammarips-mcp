# PROMPT: GammaRips MCP Server v2 — Full Tool Overhaul

## Context

The GammaRips MCP server (`/home/user/gammarips-mcp`) needs a complete tool overhaul. The current 19 tools were built for an old product that did live analysis and full-universe data ingestion. That product is dead. We now run an **Overnight Edge** pipeline that:

1. Scans institutional options flow overnight → `profitscout-fida8.profit_scout.overnight_signals` (BigQuery)
2. Enriches only score ≥ 6 signals (~85/day) with Gemini grounded search → `profitscout-fida8.profit_scout.overnight_signals_enriched` (BigQuery) AND `overnight_signals` (Firestore)
3. Tracks performance against market outcomes → `profitscout-fida8.profit_scout.signal_performance` (BigQuery) AND `signal_performance` (Firestore)
4. Generates daily reports → `daily_reports` (Firestore)
5. Will soon run Agent Arena debates → `arena_debates` (Firestore, coming later)

**The MCP API is FREE. No auth. No API key. No sign-up.** It's our top-of-funnel for AI agent discovery.

## What to Do

### 1. DELETE these tool files entirely:
- `src/tools/business_summary.py` — was pulling from old pipeline, no fresh data
- `src/tools/customer_service.py` — chatbot artifact, dead
- `src/tools/financial_analysis.py` — was doing live analysis, no fresh data
- `src/tools/fundamental_analysis.py` — same
- `src/tools/fundamental_deep_dive.py` — same (get_macro_thesis, get_mda_analysis, get_transcript_analysis)
- `src/tools/market_events.py` — no fresh data
- `src/tools/market_structure.py` — no fresh data
- `src/tools/news_analysis.py` — replaced by enrichment engine's grounded search
- `src/tools/price_data_sql.py` — no fresh price data
- `src/tools/technical_analysis.py` — replaced by enrichment engine

### 2. KEEP these tool files (but update as noted):
- `src/tools/web_search.py` — **KEEP AS-IS.** Still useful for agents doing their own research.
- `src/tools/overnight_signals.py` — **REWRITE.** See new spec below.
- `src/tools/performance_tracker.py` — **REWRITE.** See new spec below.

### 3. CREATE these NEW tool files:

#### `src/tools/overnight_signals.py` (REWRITE)

This file currently has 4 functions. Replace with 3 new ones:

**`get_overnight_signals`** — Returns raw overnight scanner signals for a given date.
- Parameters:
  - `scan_date` (optional, string, YYYY-MM-DD): Defaults to most recent scan date
  - `direction` (optional, string): "bull" or "bear" to filter
  - `min_score` (optional, int): Minimum conviction score (1-10)
  - `ticker` (optional, string): Filter to specific ticker
  - `limit` (optional, int, default 50): Max results to return
- Source: BigQuery `profitscout-fida8.profit_scout.overnight_signals`
- Query: `SELECT * FROM profit_scout.overnight_signals WHERE scan_date = @scan_date [AND direction = @direction] [AND score >= @min_score] [AND ticker = @ticker] ORDER BY score DESC LIMIT @limit`
- Returns: List of signals with fields: ticker, direction, score, volume, premium, expiration, strike, option_type, scan_date

**`get_enriched_signals`** — Returns AI-enriched signals (score ≥ 6) with news, technicals, catalyst analysis.
- Parameters:
  - `scan_date` (optional, string, YYYY-MM-DD): Defaults to most recent scan date
  - `direction` (optional, string): "bull" or "bear" to filter
  - `ticker` (optional, string): Filter to specific ticker
  - `limit` (optional, int, default 25): Max results
- Source: BigQuery `profitscout-fida8.profit_scout.overnight_signals_enriched`
- Query: `SELECT * FROM profit_scout.overnight_signals_enriched WHERE scan_date = @scan_date [AND direction = @direction] [AND ticker = @ticker] ORDER BY score DESC LIMIT @limit`
- Returns: Enriched signals with ALL fields from the table including: ticker, direction, score, news_summary, technical_context, catalyst_assessment, risk_factors, and everything else in the table

**`get_signal_detail`** — Deep dive on a single ticker from enriched data.
- Parameters:
  - `ticker` (required, string): The ticker symbol
  - `scan_date` (optional, string, YYYY-MM-DD): Defaults to most recent
- Source: BigQuery `profitscout-fida8.profit_scout.overnight_signals_enriched`
- Query: `SELECT * FROM profit_scout.overnight_signals_enriched WHERE ticker = @ticker AND scan_date = @scan_date LIMIT 1`
- Returns: Full enriched signal data for that ticker, or error message if not found

#### `src/tools/performance_tracker.py` (REWRITE)

Replace existing functions with:

**`get_signal_performance`** — Track how signals actually performed against market outcomes.
- Parameters:
  - `scan_date` (optional, string, YYYY-MM-DD): Filter to specific date
  - `ticker` (optional, string): Filter to specific ticker
  - `direction` (optional, string): "bull" or "bear"
  - `outcome` (optional, string): "win" or "loss" to filter
  - `limit` (optional, int, default 50): Max results
- Source: BigQuery `profitscout-fida8.profit_scout.signal_performance`
- Returns: Performance records with: ticker, direction, score, entry_price, current_price, pnl_pct, outcome, scan_date

**`get_win_rate_summary`** — Aggregate performance statistics.
- Parameters:
  - `days` (optional, int, default 30): Lookback period in days
- Source: BigQuery `profitscout-fida8.profit_scout.signal_performance`
- Query should calculate:
  - Total signals tracked
  - Overall win rate (%)
  - Average return (%)
  - Win rate by direction (bull vs bear)
  - Win rate by score bucket (6-7, 8-9, 10)
  - Best performing ticker
  - Worst performing ticker
- Returns: Summary statistics object

#### `src/tools/reports.py` (NEW FILE)

**`get_daily_report`** — Returns the full daily intelligence report.
- Parameters:
  - `date` (optional, string, YYYY-MM-DD): Defaults to most recent
- Source: Firestore `daily_reports` collection
- Returns: Full report with title, content (markdown), created_at, scan_date

**`get_report_list`** — List available reports.
- Parameters:
  - `limit` (optional, int, default 10): Number of reports to return
- Source: Firestore `daily_reports` collection, ordered by scan_date DESC
- Returns: List of {date, title, created_at}

#### `src/tools/metadata.py` (NEW FILE)

**`get_available_dates`** — Returns which scan dates have data available.
- Parameters: none
- Source: BigQuery `profitscout-fida8.profit_scout.overnight_signals`
- Query: `SELECT DISTINCT scan_date, COUNT(*) as signal_count FROM profit_scout.overnight_signals GROUP BY scan_date ORDER BY scan_date DESC LIMIT 30`
- Returns: List of {scan_date, signal_count}

### 4. UPDATE `src/server.py`

Replace all tool imports and registrations. The new server should register exactly **11 tools**:

```python
# Import tools
from tools.overnight_signals import get_overnight_signals, get_enriched_signals, get_signal_detail
from tools.performance_tracker import get_signal_performance, get_win_rate_summary
from tools.reports import get_daily_report, get_report_list
from tools.metadata import get_available_dates
from tools.web_search import web_search

# Register tools
mcp.tool()(get_overnight_signals)
mcp.tool()(get_enriched_signals)
mcp.tool()(get_signal_detail)
mcp.tool()(get_signal_performance)
mcp.tool()(get_win_rate_summary)
mcp.tool()(get_daily_report)
mcp.tool()(get_report_list)
mcp.tool()(get_available_dates)
mcp.tool()(web_search)
```

That's **9 tools** (we can add arena tools later when Agent Arena is deployed).

Also update the `get_tools_list()` function and any `/health` or metadata endpoints to reflect the new tool set.

### 5. Keep the existing middleware, logging, CORS, and request tracking

Don't touch:
- The Starlette middleware for CORS and request logging
- The `/health` endpoint
- The `cloudbuild.yaml` 
- The `Dockerfile`
- The `pyproject.toml` (may need to add `google-cloud-firestore` if not already there — it is)

### 6. BigQuery Connection Pattern

The existing tools already have a BigQuery client pattern. Follow the same approach:

```python
from google.cloud import bigquery

client = bigquery.Client(project="profitscout-fida8")
```

For Firestore:
```python
from google.cloud import firestore

db = firestore.Client(project="profitscout-fida8")
```

### 7. Important Notes

- **NO AUTH.** The server has no API key, no auth middleware. Don't add any.
- **All tool functions must have proper docstrings** — MCP uses these as tool descriptions for AI agents.
- **Return JSON-serializable dicts/lists** from all tools.
- **Handle errors gracefully** — return `{"error": "message"}` instead of raising exceptions.
- **Default to most recent scan_date** when no date is provided. Query: `SELECT MAX(scan_date) FROM profit_scout.overnight_signals`
- **Date format is YYYY-MM-DD** throughout.

### 8. BigQuery Table Schemas (for reference)

#### `overnight_signals` (raw scanner output)
Key fields: ticker, direction, score, volume, premium, expiration, strike, option_type, scan_date, created_at

#### `overnight_signals_enriched` (AI-enriched, score ≥ 6 only)
Key fields: everything from overnight_signals PLUS: news_summary, technical_context, catalyst_assessment, risk_factors, analyst_consensus, sector, market_cap, and more (varies — SELECT * is fine)

#### `signal_performance` (win tracker results)
Key fields: ticker, direction, score, entry_price, current_price, pnl_pct, outcome, scan_date, tracked_at

### 9. After Implementation

- Test locally: `cd /home/user/gammarips-mcp && uv pip install --system -e . && uvicorn src.server:app --host 0.0.0.0 --port 8080`
- Verify all 9 tools register on the MCP protocol
- Deploy via: `gcloud run deploy gammarips-mcp --source . --region us-central1 --project profitscout-fida8`

---

### 10. Testing & Verification (MANDATORY)

After deployment, you MUST verify every tool works end-to-end against the live Cloud Run service. Do NOT consider this task complete until all 9 tools return real data.

#### Step 1: Deploy
```bash
cd /home/user/gammarips-mcp
gcloud run deploy gammarips-mcp --source . --region us-central1 --project profitscout-fida8
```

#### Step 2: Verify MCP endpoint is live
```bash
curl -s https://gammarips-mcp-406581297632.us-central1.run.app/health
```
Expected: 200 OK with health status.

#### Step 3: Test each tool via MCP protocol

Connect to the SSE endpoint and call each tool. You can use the MCP SDK or test via direct HTTP. For each tool, verify:
1. The tool is registered and listed
2. It accepts the documented parameters
3. It returns real data from BigQuery/Firestore (not empty results or errors)

**Test each of these 9 tools with these specific calls:**

1. **`get_overnight_signals`** — Call with no params (should default to most recent date). Verify it returns signal objects with ticker, direction, score fields.

2. **`get_enriched_signals`** — Call with no params. Verify it returns enriched data with news_summary, technical_context fields populated.

3. **`get_signal_detail`** — Pick a ticker from the enriched signals result above. Call with that ticker. Verify it returns a single detailed record.

4. **`get_signal_performance`** — Call with no params. Verify it returns performance records with pnl_pct, outcome fields.

5. **`get_win_rate_summary`** — Call with `days=30`. Verify it returns aggregate stats: total_signals, win_rate, avg_return.

6. **`get_daily_report`** — Call with no params. Verify it returns a report with title and markdown content.

7. **`get_report_list`** — Call with `limit=5`. Verify it returns a list of report dates and titles.

8. **`get_available_dates`** — Call with no params. Verify it returns dates with signal counts.

9. **`web_search`** — Call with `query="AAPL stock news"`. Verify it returns search results.

#### Step 4: Report results

Print a summary table:

```
Tool                    | Status | Sample Output
------------------------|--------|------------------
get_overnight_signals   | ✅/❌  | X signals returned
get_enriched_signals    | ✅/❌  | X signals returned  
get_signal_detail       | ✅/❌  | Ticker: XXX
get_signal_performance  | ✅/❌  | X records returned
get_win_rate_summary    | ✅/❌  | Win rate: XX%
get_daily_report        | ✅/❌  | Title: "..."
get_report_list         | ✅/❌  | X reports listed
get_available_dates     | ✅/❌  | X dates available
web_search              | ✅/❌  | X results returned
```

If ANY tool fails, debug and fix before considering this done.

---

**Summary:** Delete 10 dead tool files. Rewrite 2 existing files. Create 2 new files. Update server.py. Deploy. Test all 9 tools live. Result: 9 clean tools backed by data we actually keep fresh. No auth. Free API.
