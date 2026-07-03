"""
Phase 2 auth + tiering tests. No live Firestore — the key lookup is
monkeypatched. Runnable directly:

    PYTHONPATH=src .venv/bin/python tests/test_phase2_auth.py

or via pytest.
"""

from __future__ import annotations

import sys

sys.path.insert(0, "src")

from starlette.applications import Starlette  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402
from starlette.routing import Route  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from utils import auth  # noqa: E402

# --- a valid key wired through the injectable lookup -----------------------
PRO_KEY = "gr_live_" + "a" * 32
PRO_HASH = auth.hash_key(PRO_KEY)
REVOKED_KEY = "gr_live_" + "b" * 32


def _fake_lookup(key_hash: str):
    if key_hash == PRO_HASH:
        return {"uid": "user_123", "tier": "pro", "status": "active"}
    if key_hash == auth.hash_key(REVOKED_KEY):
        return {"uid": "user_456", "tier": "pro", "status": "revoked"}
    return None


def _reset(monkey_env: dict | None = None):
    import os

    for k in ("REQUIRE_API_KEY", "AUTH_SHADOW", "ANON_TOOLS"):
        os.environ.pop(k, None)
    if monkey_env:
        os.environ.update(monkey_env)
    auth.clear_cache()


# --- build a stub app exercising the middleware ----------------------------
def _make_client():
    async def rpc(request):
        body = await request.json()
        return JSONResponse({"jsonrpc": "2.0", "id": body.get("id"), "result": {"ok": True}})

    app = Starlette(routes=[Route("/rpc", rpc, methods=["POST"])])
    app.add_middleware(auth.AccessGateMiddleware)
    return TestClient(app)


def _call(client, tool, key=None):
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    r = client.post(
        "/rpc",
        json={"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": tool}},
        headers=headers,
    )
    return r.json()


def run_all():
    results = []

    def check(name, cond, note=""):
        results.append((name, "PASS " + note if cond else f"FAIL {note}"))

    orig_lookup = auth._lookup_key
    auth._lookup_key = _fake_lookup
    try:
        # --- unit: identity resolution ---
        _reset()

        class H(dict):
            def get(self, k, d=None):
                return super().get(k.lower(), d)

        pro = auth.resolve_identity(H({"authorization": f"Bearer {PRO_KEY}"}))
        check("resolve_pro", pro.tier == "pro" and pro.uid == "user_123", f"({pro.tier})")
        anon = auth.resolve_identity(H({}))
        check("resolve_no_key", anon.tier == "anon" and anon.reason == "no_key")
        bad = auth.resolve_identity(H({"authorization": "Bearer not-a-gr-key"}))
        check("resolve_bad_format", bad.tier == "anon" and bad.reason == "bad_format")
        rev = auth.resolve_identity(H({"x-api-key": REVOKED_KEY}))
        check("resolve_revoked", rev.tier == "anon" and rev.reason == "revoked")
        unknown = auth.resolve_identity(H({"authorization": "Bearer gr_live_" + "c" * 32}))
        check("resolve_unknown", unknown.tier == "anon" and unknown.reason == "not_found")

        # lookup failure must degrade to anon, not raise
        def _boom(_):
            raise RuntimeError("firestore down")

        auth._lookup_key = _boom
        auth.clear_cache()
        degraded = auth.resolve_identity(H({"authorization": f"Bearer {PRO_KEY}"}))
        check(
            "resolve_lookup_error_anon",
            degraded.tier == "anon" and degraded.reason == "lookup_error",
        )
        auth._lookup_key = _fake_lookup

        # --- unit: tiering ---
        check("tier_anon_freemium", auth.tool_allowed("get_freemium_preview", "anon"))
        check("tier_anon_denied_pool", not auth.tool_allowed("get_pool_features", "anon"))
        check("tier_anon_denied_search", not auth.tool_allowed("web_search", "anon"))
        check("tier_pro_everything", auth.tool_allowed("get_pool_features", "pro"))

        # --- integration: OFF mode = passthrough ---
        _reset()
        client = _make_client()
        check("off_pro_tool_passes", _call(client, "get_pool_features").get("result") is not None)

        # --- integration: SHADOW = never blocks ---
        _reset({"AUTH_SHADOW": "true"})
        client = _make_client()
        check(
            "shadow_pro_tool_no_key_passes",
            _call(client, "get_pool_features").get("result") is not None,
        )

        # --- integration: ENFORCE ---
        _reset({"REQUIRE_API_KEY": "true"})
        client = _make_client()
        anon_call = _call(client, "get_freemium_preview")
        check("enforce_anon_tool_no_key_ok", anon_call.get("result") is not None)
        denied = _call(client, "get_pool_features")
        check(
            "enforce_pro_tool_no_key_denied",
            denied.get("error", {}).get("data", {}).get("code") == "subscription_required",
            f"({denied.get('error', {}).get('code')})",
        )
        allowed = _call(client, "get_pool_features", key=PRO_KEY)
        check("enforce_pro_tool_with_key_ok", allowed.get("result") is not None)
        rev_call = _call(client, "get_pool_features", key=REVOKED_KEY)
        check("enforce_revoked_key_denied", rev_call.get("error", {}).get("code") == -32001)
        # non-tool methods always pass (discovery must work for anon)
        r = client.post("/rpc", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        check("enforce_tools_list_passes", r.json().get("result") is not None)

        # --- ANON_TOOLS env override ---
        _reset({"REQUIRE_API_KEY": "true", "ANON_TOOLS": "get_overnight_signals"})
        client = _make_client()
        check(
            "env_override_makes_scan_anon",
            _call(client, "get_overnight_signals").get("result") is not None,
        )
        check(
            "env_override_freemium_now_pro",
            _call(client, "get_freemium_preview").get("error", {}).get("code") == -32001,
        )
    finally:
        auth._lookup_key = orig_lookup
        _reset()

    return results


def test_phase2_auth():
    results = run_all()
    failures = [f"{n}: {s}" for n, s in results if s.startswith("FAIL")]
    assert not failures, "\n".join(failures)


if __name__ == "__main__":
    results = run_all()
    width = max(len(n) for n, _ in results)
    fails = 0
    for name, status in results:
        print(f"{name:<{width}}  {status}")
        fails += status.startswith("FAIL")
    print(f"\n{len(results) - fails}/{len(results)} passed")
    sys.exit(1 if fails else 0)
