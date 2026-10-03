"""
Which MCP client is calling, for the few answers that must differ by client.

ChatGPT / Codex (the OpenAI plugin directory) forbid a plugin to show plans,
prices, or trial offers, or to send the user to start a subscription. A plugin
may say that a feature is not in the user's current plan and may link to an
informational page that describes the plans
(developers.openai.com/apps-sdk/app-submission-guidelines, "commerce").
Every other client keeps the full signup funnel.

A request is an OpenAI request when it comes to the `/openai` endpoint (the
URL in the ChatGPT/Codex plugin, 2026-10-03) or when it sends
`User-Agent: openai-mcp/<version>` (seen in the Cloud Run request log
2026-10-01). The path is the reliable signal: the plugin-portal scanner sends
`Python aiohttp`, not `openai-mcp`. Three answers change for it:
  * the denial envelope (utils.auth.denied_error, commerce_safe=True)
  * the connect-time `instructions` in the initialize result (server.py)
  * the signup bullets in the start-here playbook (tools.playbooks)

The tool surface, tiering, and data are identical for every client.
"""

from __future__ import annotations

from contextvars import ContextVar

from starlette.datastructures import Headers

OPENAI_UA_PREFIX = "openai-mcp"
# The plugin's own MCP URL (plugins/chatgpt/mcp.json). Same auth-required
# server as /pro (utils.oauth gateway), always commerce-safe.
OPENAI_PATH = "/openai"

# Informational plans page for the commerce-safe envelope. utm_source keeps
# ChatGPT bounces separable from the other funnels in GA4.
PLANS_URL_COMMERCE_SAFE = "https://gammarips.com/pricing?utm_source=chatgpt_plugin"

# Request-scoped flag for the code paths that have no request object (the
# FastMCP initialize options, tool implementations). asyncio tasks copy the
# context they were created in, so the MCP session task and its tool handlers
# inherit the flag of the request that opened the session.
_commerce_safe: ContextVar[bool] = ContextVar("gammarips_commerce_safe", default=False)


def is_openai_client(headers) -> bool:
    """True when the caller is OpenAI's MCP client (ChatGPT, Codex)."""
    ua = (headers.get("user-agent") or "").strip().lower()
    return ua.startswith(OPENAI_UA_PREFIX)


def is_openai_request(scope) -> bool:
    """True for the `/openai` endpoint or an OpenAI user agent."""
    if (scope.get("path") or "").rstrip("/") == OPENAI_PATH:
        return True
    return is_openai_client(Headers(scope=scope))


def commerce_safe() -> bool:
    """True inside a request (or MCP session) opened by an OpenAI client."""
    return _commerce_safe.get()


class ClientContextMiddleware:
    """Pure ASGI. Sets the commerce-safe flag for the request from its path
    and headers.

    Must be the OUTERMOST middleware so that every inner middleware, the MCP
    session manager, and the tasks it spawns see the flag."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        token = _commerce_safe.set(is_openai_request(scope))
        try:
            await self.app(scope, receive, send)
        finally:
            _commerce_safe.reset(token)
