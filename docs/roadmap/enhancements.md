# GammaRips MCP Enhancements Tracker

## Architectural Goal
To transform the MCP server into a robust decision-support system with distinct layers for "Deep Research" (Fundamentals, Financials, Business, News, Technicals) and "Trade Execution" (Winners, Opportunities).

## Tool Inventory & Status

### Tier 1: Core Research Tools (The "Parts")
These tools provide specific domains of data for a single ticker.

1.  **`news_analysis.py`**
    *   **Status**: Keep & Refine.
    *   **Source**: GCS (`enrichment/run_date=.../news_analyzer/...`).
    *   **Action**: Update docstrings to explain scoring (0-1).

2.  **`technical_analysis.py`**
    *   **Status**: Keep.
    *   **Source**: GCS (`enrichment/run_date=.../technicals_analyzer/...`).

3.  **`fundamental_analysis.py`** (**NEW**)
    *   **Status**: Create.
    *   **Source**: GCS (`gs://profit-scout-data/fundamentals-analysis/{ticker}_{date}.json`).
    *   **Purpose**: Provide key fundamental metrics.

4.  **`financial_analysis.py`** (**NEW**)
    *   **Status**: Create.
    *   **Source**: GCS (`gs://profit-scout-data/financials-analysis/{ticker}_{date}.json`).
    *   **Purpose**: Provide deep financial health analysis (Revenue, Cash Flow, Debt, Net Income).

5.  **`business_summary.py`** (**NEW**)
    *   **Status**: Create.
    *   **Source**: GCS (`gs://profit-scout-data/business-summaries/{ticker}_{date}.json`).
    *   **Purpose**: Provide qualitative business overview, subsidiaries, hubs, and strategic positioning.

6.  **`price_data_sql.py`** (**NEW**)
    *   **Status**: Create.
    *   **Source**: BigQuery (`gammarips-lx6bb.profit_scout.price_data`).
    *   **Purpose**: Allow the agent to run flexible SQL queries on raw OHLCV data (e.g., "Find volume spikes").

### Tier 2: Trade Finder Tools (The "Signals")
These tools identify specific trade setups.

7.  **`winners_dashboard.py`**
    *   **Status**: Keep.
    *   **Source**: BigQuery (`winners_dashboard`).
    *   **Purpose**: Retrieve the top ~7 high-conviction "winners" of the day.

8.  **`search_opportunities.py`**
    *   **Status**: Keep.
    *   **Source**: BigQuery (`options_analysis_signals`).
    *   **Purpose**: Search the broader pool of ~23 vetted candidates with filters (Price, DTE, etc.).

### Tier 3: The Master Tool (The "Aggregator")
This tool combines Tier 1 tools for a complete picture.

9.  **`stock_analysis.py`**
    *   **Status**: Major Update.
    *   **Purpose**: Aggregate data from Business, News, Technicals, Fundamentals, and Financials into a single comprehensive report.
    *   **Logic**: Call GCS/BQ for all 5 distinct data points and merge.

## Deletions
The following tools are redundant or being replaced:
- [ ] `options_signals.py` (Replaced by `search_opportunities` + `winners_dashboard`)
- [ ] `recommendations.py` (Removed per user request)

## Implementation Plan
1.  **Delete** the redundant tools.
2.  **Update GCS Client** to support fetching Fundamentals, Financials, and Business Summaries.
3.  **Create** `fundamental_analysis.py`, `financial_analysis.py`, and `business_summary.py`.
4.  **Create** `price_data_sql.py` with BigQuery integration.
5.  **Update** `stock_analysis.py` to aggregate the new data sources.
6.  **Verify** all docstrings provide clear context for the AI agent.
