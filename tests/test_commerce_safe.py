"""
Commerce-safe answers for OpenAI clients (ChatGPT, Codex). OpenAI's plugin
rules forbid prices, trial offers, and subscribe steps; every other client keeps
the full funnel. These tests pin both sides on the stub gate AND on the real
server app (initialize instructions, the start-here playbook through a real
MCP session, the JSON-RPC path, and the domain-verification route). No network,
no Firestore. Runnable directly:

    PYTHONPATH=src .venv/bin/python tests/test_commerce_safe.py

or via pytest.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, "src")

from starlette.applications import Starlette  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402
from starlette.routing import Route  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from utils import auth, clients  # noqa: E402

OPENAI_UA = {"User-Agent": "openai-mcp/1.0.0"}
OTHER_UA = {"User-Agent": "claude-code/2.1.0"}
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}
# Text that must never reach an OpenAI client.
FORBIDDEN = ("$29", "$39", "trial", "pricing?utm_source=mcp_", "/account", "subscribe")


def _assert_commerce_safe(text: str) -> None:
    low = text.lower()
    for bad in FORBIDDEN:
        assert bad.lower() not in low, f"{bad!r} leaked: {text[:300]}"


def _rpc(method: str, params: dict | None = None, id_: int = 1) -> dict:
    body = {"jsonrpc": "2.0", "id": id_, "method": method}
    if params is not None:
        body["params"] = params
    return body


def _sse_json(resp) -> dict:
    """Streamable HTTP answers a POST as SSE; return the first JSON-RPC message."""
    if resp.headers.get("content-type", "").startswith("application/json"):
        return resp.json()
    for line in resp.text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    raise AssertionError(f"no JSON-RPC message in: {resp.text[:300]}")


# --- detection ---------------------------------------------------------------


def test_detects_openai_user_agent_only():
    assert clients.is_openai_client({"user-agent": "openai-mcp/1.0.0"})
    assert clients.is_openai_client({"user-agent": "OpenAI-MCP/2.0"})
    assert not clients.is_openai_client({"user-agent": "claude-code/2.1.0"})
    assert not clients.is_openai_client({"user-agent": "python-httpx openai-mcp"})
    assert not clients.is_openai_client({})


def test_openai_path_is_commerce_safe_for_any_user_agent():
    scope = {
        "type": "http",
        "path": "/openai",
        "headers": [(b"user-agent", b"Python/3.14 aiohttp/3.13.5")],
    }
    assert clients.is_openai_request(scope)
    assert clients.is_openai_request({**scope, "path": "/openai/"})
    assert not clients.is_openai_request({**scope, "path": "/pro"})
    assert clients.is_openai_request(
        {"type": "http", "path": "/pro", "headers": [(b"user-agent", b"openai-mcp/1.0.0")]}
    )


# --- denial envelope ---------------------------------------------------------


def test_commerce_safe_envelope_has_no_price_trial_or_signup():
    err = auth.denied_error("query_outcomes", commerce_safe=True)
    assert err["code"] == -32001
    assert err["data"]["code"] == "subscription_required"
    assert err["data"]["plans_url"] == clients.PLANS_URL_COMMERCE_SAFE
    assert "not included in the user's current GammaRips plan" in err["message"]
    _assert_commerce_safe(json.dumps(err))


def test_full_envelope_unchanged_for_other_clients():
    err = auth.denied_error("query_outcomes")
    assert auth.PRICE in err["message"] and auth.TRIAL in err["message"]
    assert err["data"]["next_steps"]


def _gated_client() -> TestClient:
    async def rpc(request):
        body = await request.json()
        return JSONResponse({"jsonrpc": "2.0", "id": body.get("id"), "result": {"ok": True}})

    app = Starlette(
        routes=[Route("/rpc", rpc, methods=["POST"]), Route("/openai", rpc, methods=["POST"])]
    )
    app.add_middleware(auth.AccessGateMiddleware)
    app.add_middleware(clients.ClientContextMiddleware)  # outermost, as in server.py
    return TestClient(app)


def test_gate_picks_envelope_by_client():
    os.environ["REQUIRE_API_KEY"] = "true"
    auth.clear_cache()
    try:
        c = _gated_client()
        call = _rpc("tools/call", {"name": "query_outcomes", "arguments": {}}, 7)
        safe = c.post("/rpc", json=call, headers=OPENAI_UA).json()
        assert safe["id"] == 7
        assert safe["error"]["data"]["plans_url"] == clients.PLANS_URL_COMMERCE_SAFE
        _assert_commerce_safe(json.dumps(safe))
        full = c.post("/rpc", json=call, headers=OTHER_UA).json()
        assert auth.PRICE in full["error"]["message"]
        # The /openai path is commerce-safe whatever the user agent.
        by_path = c.post("/openai", json=call, headers=OTHER_UA).json()
        assert by_path["error"]["data"]["plans_url"] == clients.PLANS_URL_COMMERCE_SAFE
        _assert_commerce_safe(json.dumps(by_path))
        # A free tool still passes for an OpenAI client.
        ok = c.post(
            "/rpc",
            json=_rpc("tools/call", {"name": "get_playbook", "arguments": {}}, 8),
            headers=OPENAI_UA,
        ).json()
        assert ok["result"] == {"ok": True}
    finally:
        os.environ.pop("REQUIRE_API_KEY", None)
        auth.clear_cache()


# --- playbooks ---------------------------------------------------------------


def test_no_playbook_carries_commerce_text_for_openai_clients():
    from tools import playbooks

    token = clients._commerce_safe.set(True)
    try:
        names = [p["name"] for p in playbooks.list_playbooks()]
        assert "start-here" in names
        for name in names:
            content = playbooks.get_playbook(name)["content"]
            assert "gammarips.com/pricing" not in content, name
            assert "start the trial" not in content.lower(), name
        start = playbooks.get_playbook("start-here")["content"]
        assert playbooks._COMMERCE_SAFE_ACCESS_LINE in start
        assert start.count("subscription_required") == 1
    finally:
        clients._commerce_safe.reset(token)
    # Other clients still get the signup bullets.
    assert "gammarips.com/pricing" in playbooks.get_playbook("start-here")["content"]


# --- the real server app -----------------------------------------------------


def _server_client() -> TestClient:
    import server

    return TestClient(server.app)


def _initialize(c: TestClient, headers: dict) -> tuple[dict, str | None]:
    params = {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    }
    r = c.post("/mcp", json=_rpc("initialize", params), headers={**MCP_HEADERS, **headers})
    assert r.status_code == 200, r.text[:300]
    return _sse_json(r), r.headers.get("mcp-session-id")


def test_streamable_initialize_and_playbook_by_client():
    import server

    with _server_client() as c:
        msg, session = _initialize(c, OPENAI_UA)
        assert msg["result"]["instructions"] == server._INSTRUCTIONS_COMMERCE_SAFE
        _assert_commerce_safe(msg["result"]["instructions"])

        # A tool call in that session runs in the session's context: the
        # start-here playbook must come back commerce-safe.
        h = {**MCP_HEADERS, **OPENAI_UA}
        if session:
            h["mcp-session-id"] = session
        c.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=h)
        r = c.post(
            "/mcp",
            json=_rpc(
                "tools/call", {"name": "get_playbook", "arguments": {"name": "start-here"}}, 2
            ),
            headers=h,
        )
        text = json.dumps(_sse_json(r))
        assert "How access works" in text
        assert "gammarips.com/pricing" not in text

        msg, _ = _initialize(c, OTHER_UA)
        assert msg["result"]["instructions"] == server._INSTRUCTIONS


def test_jsonrpc_initialize_by_client():
    import server

    c = _server_client()
    safe = c.post("/jsonrpc", json=_rpc("initialize", {}), headers=OPENAI_UA).json()
    assert safe["result"]["instructions"] == server._INSTRUCTIONS_COMMERCE_SAFE
    full = c.post("/jsonrpc", json=_rpc("initialize", {}), headers=OTHER_UA).json()
    assert full["result"]["instructions"] == server._INSTRUCTIONS


def test_openai_apps_challenge_route():
    c = _server_client()
    os.environ.pop("OPENAI_APPS_CHALLENGE", None)
    assert c.get("/.well-known/openai-apps-challenge").status_code == 404
    os.environ["OPENAI_APPS_CHALLENGE"] = "tok_abc123\n"
    try:
        r = c.get("/.well-known/openai-apps-challenge")
        assert r.status_code == 200
        assert r.text == "tok_abc123"
        assert r.headers["content-type"].startswith("text/plain")
    finally:
        os.environ.pop("OPENAI_APPS_CHALLENGE", None)


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"FAIL {name}: {e!r}")
    sys.exit(1 if failed else 0)
