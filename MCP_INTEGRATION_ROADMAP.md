# GammaRips / GammaRips MCP Integration Roadmap

## Objective
To transform **GammaRips** from an internal backend service into a dual-purpose product:
1.  **"Headless" TaaS (Tools as a Service):** Allowing paid users to plug our financial data tools directly into their own AI agents (Claude Desktop, Cursor, custom bots).
2.  **Web Agent:** Powering an on-site chat interface at `gammarips.com`.

---

## Phase 1: The "Headless" Onboarding (Immediate Priority)
*Target Audience: Power Users, Developers, Algo Traders.*

### 1.1 Secure the MCP Server
**Goal:** Restrict tool access to valid paid subscribers.
*   **Authentication:** Implement `API Key` validation middleware on the GammaRips MCP server.
    *   *Mechanism:* Request headers must include `X-API-Key: <sk_user_key>`.
    *   *Validation:* Verify keys against a user database (Firestore/Supabase).
*   **Rate Limiting:** Protect backend resources (BigQuery costs) by limiting tool calls per minute/day per key.

### 1.2 The "Connect" Dashboard
**Goal:** Self-serve configuration for users.
*   **Location:** New page at `gammarips.com/connect` (or `/developers`).
*   **Features:**
    *   **API Key Management:** "Generate New Key", "Revoke Key".
    *   **Configuration Snippets:** One-click copy for `claude_desktop_config.json` and `.env` files.
    *   **Endpoint Display:** Clear display of the user's dedicated SSE (Server-Sent Events) URL: `https://api.gammarips.com/sse`
*   **Connection Tester:** A simple "Ping" button on the web page to verify the API key is active.

### 1.3 Tool Catalog & Documentation
**Goal:** Teach users (and their agents) *how* to use the tools.
*   **Live Docs:** Auto-generated page listing all 15+ available tools.
    *   *Example:* `get_winners_dashboard`: "Returns today's top high-gamma options setups."
*   **Prompt Library:** Provide "Starter Prompts" users can paste into their agents.
    *   *Example:* "Analyze the gamma walls for SPY and tell me if we are in a bullish trend."

---

## Phase 2: The "Embedded" Web Agent
*Target Audience: General Retail Traders.*

### 2.1 On-Site Chat Interface
**Goal:** "Chat with GammaRips" directly in the browser.
*   **Architecture:**
    *   **Frontend:** React/Next.js Chat UI.
    *   **Middle Layer:** The `gammarips.com` backend acts as the **MCP Host**. It manages the conversation history and calls the GammaRips MCP server tools on behalf of the user.
    *   **Model:** Connects to a fast, reasoning model (e.g., Gemini 2.0 Flash or Claude 3.5 Sonnet).
*   **UX:** seamless streaming responses with rich formatting (Markdown tables for data).

---

## Technical Requirements for Web Team

### Frontend (gammarips.com)
*   **New Route:** `/connect` (Protected, Paid Users Only).
*   **UI Components:**
    *   API Key Generator (Copy/Revoke).
    *   Code Block display for JSON configs.
    *   Tool List visualization (Name, Description, Parameters).

### Backend (GammaRips MCP)
*   **Auth Middleware:** Verify `X-API-Key` headers.
*   **CORS Configuration:** Allow requests from local agents (checking origins or strictly enforcing header auth).
*   **Usage Tracking:** Log tool usage per API key for billing/monitoring.

---

## User Journey: The "Headless" Setup

1.  **User** logs into `gammarips.com`.
2.  **User** navigates to "Connect Agent".
3.  **User** generates an API Key: `sk_live_12345...`.
4.  **User** copies the "Claude Desktop Config" snippet.
5.  **User** pastes snippet into their local computer's config file.
6.  **User** opens Claude Desktop and asks: *"Check the market winners for today."*
7.  **Result:** Claude connects to GammaRips, fetches real-time BigQuery data, and explains the trade setups.
