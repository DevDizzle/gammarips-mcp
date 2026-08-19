"""
OAuth 2.1 resource-server tests: the /pro gateway, JWT verification, the
discovery documents, and the tier mapping. No network — the JWKS cache is
preloaded with a test key and the AS-metadata mirror is stubbed. Runnable
directly:

    PYTHONPATH=src .venv/bin/python tests/test_oauth_pro.py

or via pytest.
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, "src")

import jwt  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from starlette.applications import Starlette  # noqa: E402
from starlette.requests import Request  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402
from starlette.routing import Route  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from utils import auth, oauth  # noqa: E402

ISSUER = "https://gammarips.com"
AUD = "https://mcp.gammarips.com/pro"
KID = "test-2026"

# --- keys ------------------------------------------------------------------
_priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_priv_pem = _priv.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
)
_pub_jwk = jwt.algorithms.RSAAlgorithm.to_jwk(_priv.public_key(), as_dict=True)
_pub_jwk.update({"kid": KID, "use": "sig", "alg": "RS256"})
_other_priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_other_pem = _other_priv.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
)


def mint(
    tier="pro",
    aud=AUD,
    iss=ISSUER,
    exp_in=3600,
    kid=KID,
    key=_priv_pem,
    alg="RS256",
    client_kind="user",
    extra=None,
    sub="uid_abc",
    typ="at+jwt",
):
    now = int(time.time())
    claims = {
        "iss": iss,
        "sub": sub,
        "aud": aud,
        "iat": now,
        "nbf": now - 5,
        "exp": now + exp_in,
        "jti": "jti-12345678",
        "client_id": "https://claude.ai/oauth/claude-code-client-metadata",
        "scope": "mcp:read",
        "tier": tier,
        "grant": "authorization_code",
        "client_kind": client_kind,
    }
    if extra:
        claims.update(extra)
    headers = {"kid": kid, "typ": typ} if typ is not None else {"kid": kid}
    return jwt.encode(claims, key, algorithm=alg, headers=headers)


# --- API key fixture -------------------------------------------------------
PRO_KEY = "gr_live_" + "a" * 32


def _fake_lookup(key_hash: str):
    if key_hash == auth.hash_key(PRO_KEY):
        return {"uid": "user_123", "tier": "pro", "status": "active"}
    return None


def _reset(env: dict | None = None):
    for k in ("REQUIRE_API_KEY", "AUTH_SHADOW", "ANON_TOOLS", "OAUTH_ENABLED", "OAUTH_ISSUER"):
        os.environ.pop(k, None)
    os.environ["REQUIRE_API_KEY"] = "true"
    if env:
        os.environ.update(env)
    auth.clear_cache()
    oauth.jwks_cache().reset()
    oauth.jwks_cache().preload({KID: jwt.PyJWK(_pub_jwk)})


# --- stub app: /mcp echoes; middleware stack mirrors server.py order -------
def _make_client():
    async def mcp(request: Request):
        body = await request.json()
        ident = getattr(request.state, "identity", None)
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": body.get("id"),
                "result": {
                    "path": request.url.path,
                    "endpoint": request.scope.get(oauth.SCOPE_ENDPOINT_KEY, "mcp"),
                    "client_class": ident.client_class if ident else None,
                    "tier": ident.tier if ident else None,
                },
            }
        )

    app = Starlette(
        routes=[
            Route("/mcp", mcp, methods=["POST"]),
            Route("/.well-known/oauth-protected-resource", oauth.protected_resource_metadata),
            Route(
                "/.well-known/oauth-protected-resource/{suffix:path}",
                oauth.protected_resource_metadata,
            ),
            Route("/.well-known/oauth-authorization-server", oauth.authorization_server_metadata),
        ]
    )
    # add_middleware is LIFO: AccessGate inner, ProEndpoint outer — same as server.py.
    app.add_middleware(auth.AccessGateMiddleware)
    app.add_middleware(oauth.ProEndpointMiddleware)
    return TestClient(app)


def _call(client, path, tool, token=None, arguments=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    params = {"name": tool}
    if arguments is not None:
        params["arguments"] = arguments
    return client.post(
        path,
        json={"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": params},
        headers=headers,
    )


def test_oauth_pro():
    auth._lookup_key = _fake_lookup  # noqa: SLF001
    _reset()
    c = _make_client()

    # 1. /pro without any credential: 401 + discovery challenge, no error= param.
    r = _call(c, "/pro", "get_pool")
    assert r.status_code == 401, r.text
    www = r.headers["www-authenticate"]
    assert www.startswith("Bearer ")
    assert 'resource_metadata="http://testserver/.well-known/oauth-protected-resource/pro"' in www
    assert 'scope="mcp:read"' in www
    assert "error=" not in www
    assert r.json()["error"] == "unauthorized"

    # 2. /pro with garbage: 401 + error="invalid_token".
    r = _call(c, "/pro", "get_pool", token="not-a-token")
    assert r.status_code == 401
    assert 'error="invalid_token"' in r.headers["www-authenticate"]
    # a well-formed JWT signed by an unknown key: same
    r = _call(c, "/pro", "get_pool", token=mint(key=_other_pem))
    assert r.status_code == 401
    r = _call(c, "/pro", "get_pool", token=mint(kid="nope"))
    assert r.status_code == 401

    # 3. Valid pro token: path rewritten to /mcp, pro tool allowed, identity carried.
    r = _call(c, "/pro", "get_signal", token=mint())
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert res["path"] == "/mcp"
    assert res["endpoint"] == "pro"
    assert res["client_class"] == "oauth_user"
    assert res["tier"] == "pro"

    # 4. Valid FREE token: admitted to /pro (it is a real credential), but the
    # pro tool bounces with the upgrade envelope; the free tool works.
    r = _call(c, "/pro", "get_signal", token=mint(tier="free"))
    assert r.status_code == 200
    assert r.json()["error"]["data"]["code"] == "subscription_required"
    r = _call(c, "/pro", "get_pool", token=mint(tier="free"), arguments={"view": "preview"})
    assert r.status_code == 200 and "result" in r.json()
    assert r.json()["result"]["tier"] == "anon"
    # tier is fail-closed on privilege: anything that is not "pro" (after the
    # same strip/lower the key path applies) is anon
    for weird in ("admin", "pro-plus", "", None, 1, True):
        r = _call(c, "/pro", "get_signal", token=mint(tier=weird))
        assert r.json().get("error", {}).get("data", {}).get("code") == "subscription_required", (
            weird
        )

    # 5. Rejections: expired, wrong aud, wrong iss, alg confusion, no sub.
    assert oauth.verify_access_token(mint(exp_in=-3600)) is None
    assert oauth.verify_access_token(mint(aud="https://evil.example/pro")) is None
    assert oauth.verify_access_token(mint(aud="https://mcp.gammarips.com/other")) is None
    assert oauth.verify_access_token(mint(iss="https://evil.example")) is None
    assert oauth.verify_access_token(mint(sub="")) is None
    hs = jwt.encode(
        {
            "iss": ISSUER,
            "sub": "x",
            "aud": AUD,
            "exp": int(time.time()) + 60,
            "iat": int(time.time()),
            "tier": "pro",
        },
        "secret",
        algorithm="HS256",
        headers={"kid": KID},
    )
    assert oauth.verify_access_token(hs) is None
    # typ must be at+jwt (RFC 9068): a plain JWT or another type is not an access token
    assert oauth.verify_access_token(mint(typ="JWT")) is None
    assert oauth.verify_access_token(mint(typ=None)) is None
    # accepted audiences include the root and /mcp forms and the run.app hosts
    assert oauth.verify_access_token(mint(aud="https://mcp.gammarips.com")) is not None
    assert oauth.verify_access_token(mint(aud="https://mcp.gammarips.com/mcp")) is not None
    assert (
        oauth.verify_access_token(
            mint(aud="https://gammarips-mcp-406581297632.us-central1.run.app/pro")
        )
        is not None
    )
    # aud may be a list; any allowed member suffices
    assert oauth.verify_access_token(mint(aud=["https://x.example", AUD])) is not None
    # 60s leeway: a token that expired 30s ago still passes, 120s ago does not
    assert oauth.verify_access_token(mint(exp_in=-30)) is not None
    assert oauth.verify_access_token(mint(exp_in=-120)) is None

    # 6. API key works on /pro too (same gate), and is an api_key client class.
    r = _call(c, "/pro", "get_signal", token=PRO_KEY)
    assert r.status_code == 200 and r.json()["result"]["client_class"] == "api_key"
    # revoked/unknown key is NOT a credential: 401 on /pro
    r = _call(c, "/pro", "get_signal", token="gr_live_" + "f" * 32)
    assert r.status_code == 401

    # 7. JWT on the anonymous /mcp endpoint: honored like a key; endpoint stays "mcp".
    r = _call(c, "/mcp", "get_signal", token=mint())
    assert r.status_code == 200 and r.json()["result"]["endpoint"] == "mcp"
    assert r.json()["result"]["client_class"] == "oauth_user"
    # machine tokens are their own class
    r = _call(c, "/mcp", "get_signal", token=mint(client_kind="machine"))
    assert r.json()["result"]["client_class"] == "oauth_machine"
    # /mcp without a credential still serves the free tool (funnel unchanged)
    r = _call(c, "/mcp", "get_pool", arguments={"view": "preview"})
    assert r.status_code == 200 and "result" in r.json()

    # 8. Discovery documents.
    r = c.get("/.well-known/oauth-protected-resource")
    assert r.status_code == 200
    d = r.json()
    assert d["resource"] == "http://testserver"
    assert d["authorization_servers"] == [ISSUER]
    assert d["scopes_supported"] == ["mcp:read"]
    r = c.get("/.well-known/oauth-protected-resource/pro")
    assert r.status_code == 200 and r.json()["resource"] == "http://testserver/pro"
    r = c.get("/.well-known/oauth-protected-resource/mcp")
    assert r.status_code == 200 and r.json()["resource"] == "http://testserver/mcp"
    assert c.get("/.well-known/oauth-protected-resource/nope").status_code == 404
    oauth.set_as_metadata_for_tests(None)
    assert c.get("/.well-known/oauth-authorization-server").status_code == 503
    oauth.set_as_metadata_for_tests({"issuer": ISSUER, "token_endpoint": ISSUER + "/oauth/token"})
    r = c.get("/.well-known/oauth-authorization-server")
    assert r.status_code == 200 and r.json()["issuer"] == ISSUER

    # 9. Verification runs once per request (the gateway hands the identity down).
    calls = {"n": 0}
    real = oauth.verify_access_token

    def counting(tok):
        calls["n"] += 1
        return real(tok)

    auth.verify_access_token = counting  # the name auth.py bound at import
    try:
        _call(c, "/pro", "get_signal", token=mint())
        assert calls["n"] == 1, calls
    finally:
        auth.verify_access_token = real

    # 10. Master switch off: no JWTs, no /pro, no discovery.
    _reset({"OAUTH_ENABLED": "false"})
    c2 = _make_client()
    # (a non-tool body, so the access gate does not answer before routing)
    assert (
        c2.post("/pro", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"}).status_code == 404
    )
    assert c2.get("/.well-known/oauth-protected-resource/pro").status_code == 404
    r = _call(c2, "/mcp", "get_signal", token=mint())
    assert r.json()["error"]["data"]["code"] == "subscription_required"
    ident = auth.resolve_identity({"authorization": f"Bearer {mint()}"})
    assert ident.tier == "anon" and ident.client_class == "none" and ident.reason == "bad_format"

    # 11. Shape gate.
    assert oauth.looks_like_jwt(mint())
    assert not oauth.looks_like_jwt("gr_live_" + "a" * 32)
    assert not oauth.looks_like_jwt("a.b")
    assert not oauth.looks_like_jwt("a.b.c")
    assert not oauth.looks_like_jwt("")

    _reset()
    print("test_oauth_pro: OK")


if __name__ == "__main__":
    test_oauth_pro()
