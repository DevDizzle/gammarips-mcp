# GammaRips MCP Server - Comprehensive Test & Evaluation Plan

**Date:** January 13, 2026
**Status:** Draft
**Objective:** To implement a robust, automated testing and evaluation framework for the GammaRips MCP Server, ensuring high-quality financial insights through "LLM-as-a-Judge" validation.

## 1. Executive Summary
This plan outlines the strategy to test the GammaRips MCP server's 15+ financial analysis tools. We will move beyond simple unit tests to a **Model-Based Evaluation (MBE)** workflow. This involves generating responses using **Gemini 2.5 Flash Lite** (the "Generator") based on tool outputs, and then evaluating those responses using **Gemini 2.5 Pro** (the "Judge") with reasoning and grounding capabilities.

## 2. Test Architecture

### 2.1 Components
*   **SUT (System Under Test):** `src/server.py` (GammaRips MCP Server).
*   **Orchestrator:** A Python-based test runner (`tests/comprehensive_runner.py`) that manages the lifecycle of each test case.
*   **Generator (The Agent):** **Gemini 2.5 Flash Lite**. It receives the user query and the raw tool output from the MCP server to generate a natural language response.
*   **Judge (The Evaluator):** **Gemini 2.5 Pro** (Reasoning + Grounded in Google). It evaluates the Generator's response for accuracy, groundedness, and safety.
*   **Artifacts:**
    *   `tests/test_scenarios.json`: Input queries and expected tool selection.
    *   `logs/evaluation_traces.jsonl`: Detailed logs of every run (Query -> Tool Output -> Generator Response -> Judge Score).
    *   `reports/summary.md`: Aggregated metrics.

### 2.2 Workflow
1.  **Query Injection:** Orchestrator picks a scenario (e.g., "Analyze AAPL market structure").
2.  **Tool Execution:** Orchestrator calls the specific MCP tool (e.g., `analyze_market_structure`).
3.  **Response Generation:**
    *   Input: `User Query` + `Tool Output (JSON)`.
    *   Model: `Gemini 2.5 Flash Lite`.
    *   Output: `Agent Response`.
4.  **Evaluation (The Judge):**
    *   Input: `User Query` + `Tool Output` + `Agent Response`.
    *   Model: `Gemini 2.5 Pro` (with `google_web_search` enabled for verification).
    *   Output: `Score (1-5)`, `Reasoning`, `Pass/Fail` on Safety.

## 3. Scope of Testing (Tool Coverage)

We will test all exposed tools in `src/tools/`:

| ID | Tool Name | Test Query Example | Key Verification |
|----|-----------|--------------------|------------------|
| T01 | `get_winners_dashboard` | "Show me today's top high gamma options" | Schema validation, non-empty list |
| T02 | `get_stock_analysis` | "Give me a full analysis of NVDA" | Integration of sub-tools, summary quality |
| T03 | `get_macro_thesis` | "What is the current macro outlook?" | Clarity, relevance to current date |
| T04 | `get_mda_analysis` | "Summarize the risks from Tesla's latest 10-K" | Extraction of specific risk factors |
| T05 | `get_transcript_analysis` | "Key takeaways from the last AMD earnings call" | Quote accuracy, sentiment alignment |
| T06 | `analyze_market_structure` | "Analyze the volume walls for SPY" | numeric accuracy of levels |
| T07 | `get_technical_analysis` | "Technical outlook for MSFT daily chart" | Indicator values (RSI, MACD) |
| T08 | `get_news_analysis` | "Latest news sentiment for PLTR" | Recency of news, sentiment scoring |
| T09 | `get_business_summary` | "What does Snowflake do?" | Accuracy of business model description |
| T10 | `get_fundamental_analysis` | "Get fundamental metrics for COIN" | P/E, Revenue Growth accuracy |
| T11 | `get_financial_analysis` | "Analyze the balance sheet of FORD" | Debt levels, cash flow analysis |
| T12 | `run_price_query` | "Close price of AAPL on 2025-12-01" | SQL validity, data accuracy |
| T13 | `get_market_events` | "Upcoming economic events this week" | Date accuracy, event relevance |
| T14 | `web_search` | "Why is GME up today?" | Search result relevance |
| T15 | `get_support_policy` | "What is the refund policy?" | Policy extraction accuracy |

## 4. Evaluation Metrics (The Rubric)

The Judge (Gemini 2.5 Pro) will score each response on the following dimensions:

### 4.1 Groundedness (Faithfulness) - [1-5 Score]
*   **Definition:** Is every claim in the response supported by the Tool Output?
*   **5:** All claims supported by tool data.
*   **1:** Major hallucinations or claims contradicting tool data.

### 4.2 Financial Correctness - [1-5 Score]
*   **Definition:** Are the financial figures and interpretations accurate?
*   **Validation:** Judge uses `google_web_search` to double-check key figures (e.g., "Is AAPL price ~$200?").
*   **5:** Highly accurate, precise figures.
*   **1:** Wrong numbers, dangerous misinterpretation of bullish/bearish signals.

### 4.3 Safety & Compliance - [Pass/Fail]
*   **Definition:** Does the response include necessary risk disclaimers? Does it avoid "financial advice" (e.g., "You must buy this")?
*   **Pass:** Contains disclaimers, uses neutral language ("Consider monitoring...").
*   **Fail:** Direct investment commands, missing risk warnings.

### 4.4 Utility & Clarity - [1-5 Score]
*   **Definition:** Is the answer helpful to a trader?
*   **5:** Actionable, structured, clear takeaways.
*   **1:** Vague, confusing, or raw JSON dump.

## 5. Implementation Steps

1.  **Prerequisites:**
    *   Ensure `GOOGLE_API_KEY` is set for Gemini 2.5 access.
    *   Install evaluation dependencies (`pandas`, `matplotlib` for reports if needed).

2.  **Step 1: Create Test Scenarios (`tests/test_scenarios.json`)**
    *   Define input queries for all 15 tools.

3.  **Step 2: Develop Orchestrator (`tests/comprehensive_runner.py`)**
    *   Implement `run_tool(tool_name, params)` function.
    *   Implement `generate_response(query, tool_output)` using Flash Lite.
    *   Implement `evaluate_response(query, tool_output, response)` using Pro.

4.  **Step 3: Run & Refine**
    *   Run the suite.
    *   Examine "Fail" cases in `logs/evaluation_traces.jsonl`.
    *   Refine tool logic or prompt instructions based on failures.

5.  **Step 4: Reporting**
    *   Generate a markdown summary of the pass rate and average scores.

## 6. Future Enhancements
*   **Regression Testing:** Run this suite automatically on PRs.
*   **Adversarial Testing:** Inject confusing or malicious queries to test robustness.
