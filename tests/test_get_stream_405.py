"""
GET /mcp -> 405 (NoGetStreamMiddleware, 2026-09-28). The MCP spec lets a server
refuse the client's optional GET stream with 405. Before this, bot-held GET
streams billed the Cloud Run instance for ~99% of its request time. These tests
pin that the GET is refused at once, that POST traffic (initialize, tools/list)
is untouched on a real FastMCP Streamable HTTP app, and that the env-var
rollback restores pass-through. No network. Runnable directly:

    PYTHONPATH=src .venv/bin/python tests/test_get_stream_405.py

or via pytest.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, "src")

from mcp.server.fastmcp import FastMCP  # noqa: E402
from starlette.applications import Starlette  # noqa: E402
from starlette.responses import PlainTextResponse  # noqa: E402
from starlette.routing import Route  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from utils.safety import NoGetStreamMiddleware  # noqa: E402

SSE_ACCEPT = {"Accept": "application/json, text/event-stream"}


def _stub_app() -> Starlette:
    async def ok(request):
        return PlainTextResponse("passed-through")

    app = Starlette(routes=[Route("/{p:path}", ok, methods=["GET", "POST", "DELETE"])])
    app.add_middleware(NoGetStreamMiddleware)
    return app


def test_get_on_mcp_is_refused_with_405():
    c = TestClient(_stub_app())
    for path in ("/mcp", "/mcp/"):
        r = c.get(path, headers={"Accept": "text/event-stream"})
        assert r.status_code == 405, path
        assert r.headers["allow"] == "POST, DELETE"
        assert r.json()["error"]["code"] == -32000


def test_other_methods_and_paths_pass_through():
    c = TestClient(_stub_app())
    assert c.post("/mcp").text == "passed-through"
    assert c.delete("/mcp").text == "passed-through"
    assert c.get("/sse").text == "passed-through"
    assert c.get("/.well-known/mcp/server-card.json").text == "passed-through"


def test_env_flag_restores_the_get_stream():
    os.environ["MCP_GET_STREAM_ENABLED"] = "true"
    try:
        c = TestClient(_stub_app())
        assert c.get("/mcp").text == "passed-through"
    finally:
        del os.environ["MCP_GET_STREAM_ENABLED"]


def test_real_streamable_app_keeps_post_working():
    # host="0.0.0.0" as in src/server.py; the default 127.0.0.1 turns on the
    # SDK's DNS-rebinding guard, which 421s the TestClient host.
    mcp = FastMCP(name="t", host="0.0.0.0")

    @mcp.tool()
    def ping() -> str:
        return "pong"

    app = mcp.streamable_http_app()
    app.add_middleware(NoGetStreamMiddleware)

    with TestClient(app) as c:
        init = c.post(
            "/mcp",
            headers=SSE_ACCEPT,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0"},
                },
            },
        )
        assert init.status_code == 200
        sid = init.headers["mcp-session-id"]
        hdrs = {**SSE_ACCEPT, "mcp-session-id": sid, "mcp-protocol-version": "2025-06-18"}

        c.post("/mcp", headers=hdrs, json={"jsonrpc": "2.0", "method": "notifications/initialized"})

        # The GET a client opens after initialize is refused at once.
        get = c.get("/mcp", headers={**hdrs, "Accept": "text/event-stream"})
        assert get.status_code == 405

        # The session is intact: tools/list still answers over POST.
        tl = c.post("/mcp", headers=hdrs, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert tl.status_code == 200
        assert '"ping"' in tl.text


if __name__ == "__main__":
    test_get_on_mcp_is_refused_with_405()
    test_other_methods_and_paths_pass_through()
    test_env_flag_restores_the_get_stream()
    test_real_streamable_app_keeps_post_working()
    print("OK: 4 passed")
