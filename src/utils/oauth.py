"""
OAuth 2.1 RESOURCE-SERVER side for the GammaRips MCP (MCP authorization spec
2026-07-28; decision: docs/DECISIONS/2026-08-15-oauth-pro-endpoint.md).

  * gammarips.com is the AUTHORIZATION SERVER (issuer). It signs RS256 access
    tokens and publishes the public keys at {issuer}/oauth/jwks. This service
    only VERIFIES: it holds no OAuth state, writes nothing, and never mints.
  * `/pro` is the auth-required MCP endpoint: any request without a VALID
    credential (API key or JWT) gets a 401 with the RFC 9728 discovery header,
    which is what makes a chat client (ChatGPT, claude.ai, Cursor) start the
    OAuth flow. With a valid credential the request is the same Streamable HTTP
    transport as `/mcp` (the path is rewritten in-process).
  * `/mcp` stays anonymous: the free funnel never regresses. A JWT sent to
    `/mcp` is honored exactly like an API key.
  * Tier comes from the token's `tier` claim (stamped by the AS from the live
    subscription, re-checked on every refresh / machine mint). Anything that is
    not exactly `pro` is anon — fail-closed on privilege, same as keys.
  * Audience: the token's `aud` must be one of OUR resource URIs (RFC 8707);
    tokens minted for anything else are rejected. Token passthrough: none.

Env (all optional; defaults are production):
  OAUTH_ENABLED=true|false       master switch (false: JWTs rejected, /pro 404)
  OAUTH_ISSUER                   default https://gammarips.com
  OAUTH_JWKS_URL                 default {issuer}/oauth/jwks
  OAUTH_MCP_RESOURCE_ORIGINS     comma list; default the three live hosts
"""

from __future__ import annotations

import base64
import json
import logging
import os
import threading
import time
from typing import Any

import httpx
import jwt
from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

PRO_PATH = "/pro"
MCP_PATH = "/mcp"
SCOPE = "mcp:read"
RESOURCE_PATHS = ("", "/pro", "/mcp")
ALGORITHMS = ("RS256",)
_LEEWAY_SECONDS = 60
_JWKS_TIMEOUT = 3.0
_JWKS_TTL = 3600.0
_JWKS_REFETCH_COOLDOWN = 60.0
_AS_META_TTL = 600.0

# Scope key for the identity the /pro gateway resolved, so the access gate
# does not verify the same token twice. Not `scope["state"]` — that dict is
# Starlette's lifespan state; we keep our own key.
SCOPE_IDENTITY_KEY = "gammarips_identity"
SCOPE_ENDPOINT_KEY = "gammarips_endpoint"


def oauth_enabled() -> bool:
    return os.getenv("OAUTH_ENABLED", "true").strip().lower() == "true"


def issuer() -> str:
    return os.getenv("OAUTH_ISSUER", "https://gammarips.com").strip().rstrip("/")


def jwks_url() -> str:
    return os.getenv("OAUTH_JWKS_URL", "").strip() or f"{issuer()}/oauth/jwks"


def resource_origins() -> tuple[str, ...]:
    raw = os.getenv(
        "OAUTH_MCP_RESOURCE_ORIGINS",
        "https://mcp.gammarips.com,"
        "https://gammarips-mcp-406581297632.us-central1.run.app,"
        "https://gammarips-mcp-hrhjaecvhq-uc.a.run.app",
    )
    return tuple(o.strip().rstrip("/").lower() for o in raw.split(",") if o.strip())


def allowed_audiences() -> list[str]:
    return [o + p for o in resource_origins() for p in RESOURCE_PATHS]


# --- token shape -----------------------------------------------------------


def _b64url_json(segment: str) -> dict | None:
    try:
        pad = "=" * (-len(segment) % 4)
        raw = base64.urlsafe_b64decode(segment + pad)
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except Exception:  # noqa: BLE001
        return None


def looks_like_jwt(token: str) -> bool:
    """Three base64url segments and a JOSE header with an `alg`. Cheap gate so
    garbage bearer strings never reach the verifier."""
    if not token or len(token) > 8192 or token.count(".") != 2:
        return False
    head = _b64url_json(token.split(".")[0])
    return bool(head and isinstance(head.get("alg"), str))


# --- JWKS cache ------------------------------------------------------------


class _JwksCache:
    """Keys by kid. A miss refetches at most once per cooldown window, so a
    flood of tokens with made-up kids cannot turn this service into a request
    amplifier against the issuer. Never raises."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._keys: dict[str, Any] = {}
        self._fetched_at = 0.0
        self._last_attempt = 0.0

    def _fetch_locked(self) -> None:
        now = time.monotonic()
        if now - self._last_attempt < _JWKS_REFETCH_COOLDOWN:
            return
        self._last_attempt = now
        try:
            resp = httpx.get(
                jwks_url(), timeout=_JWKS_TIMEOUT, headers={"Accept": "application/json"}
            )
            resp.raise_for_status()
            data = resp.json()
            keys: dict[str, Any] = {}
            for k in data.get("keys", []):
                if k.get("kty") == "RSA" and k.get("kid"):
                    keys[str(k["kid"])] = jwt.PyJWK(k)
            if keys:
                self._keys = keys
                self._fetched_at = now
            else:
                logger.warning("oauth: JWKS at %s had no RSA keys", jwks_url())
        except Exception as e:  # noqa: BLE001
            logger.warning("oauth: JWKS fetch failed (%s)", e)

    def get(self, kid: str):
        with self._lock:
            stale = time.monotonic() - self._fetched_at > _JWKS_TTL
            if kid not in self._keys or stale:
                self._fetch_locked()
            return self._keys.get(kid)

    def reset(self) -> None:
        with self._lock:
            self._keys = {}
            self._fetched_at = 0.0
            self._last_attempt = 0.0

    def preload(self, keys: dict[str, Any]) -> None:
        """Test seam: install keys without a network fetch."""
        with self._lock:
            self._keys = dict(keys)
            self._fetched_at = time.monotonic()
            self._last_attempt = self._fetched_at


_jwks = _JwksCache()


def jwks_cache() -> _JwksCache:
    return _jwks


# --- verification ----------------------------------------------------------


def verify_access_token(token: str) -> dict | None:
    """Return the claims of a valid token minted by OUR issuer for OUR
    resource, else None. Never raises. Checks: RS256 + typ at+jwt + known kid,
    signature, exp/nbf/iat (60s leeway), iss, aud ∈ allowed_audiences, sub."""
    if not oauth_enabled():
        return None
    try:
        header = jwt.get_unverified_header(token)
    except Exception:  # noqa: BLE001
        return None
    if header.get("alg") not in ALGORITHMS:
        return None
    # RFC 9068: only ACCESS tokens (typ at+jwt) are accepted here, so no other
    # JWT the issuer may ever sign with the same key can be replayed as one.
    if header.get("typ") != "at+jwt":
        return None
    kid = header.get("kid")
    if not isinstance(kid, str) or not kid:
        return None
    key = _jwks.get(kid)
    if key is None:
        logger.info("oauth: token with unknown kid rejected")
        return None
    try:
        claims = jwt.decode(
            token,
            key=key.key,
            algorithms=list(ALGORITHMS),
            issuer=issuer(),
            audience=allowed_audiences(),
            leeway=_LEEWAY_SECONDS,
            options={"require": ["exp", "iat", "sub", "aud", "iss"]},
        )
    except jwt.PyJWTError as e:
        logger.info("oauth: token rejected (%s)", type(e).__name__)
        return None
    if not isinstance(claims.get("sub"), str) or not claims["sub"]:
        return None
    return claims


# --- discovery documents (RFC 9728 + RFC 8414 pass-through) ---------------


def _base_url(request: Request) -> str:
    """Scheme + host as the CLIENT sees them. uvicorn runs with
    --proxy-headers so X-Forwarded-Proto from Cloud Run sets the scheme."""
    scheme = request.url.scheme
    host = request.headers.get("host") or request.url.netloc
    return f"{scheme}://{host}".rstrip("/")


def protected_resource_metadata_doc(base: str, path: str) -> dict:
    return {
        "resource": base + path,
        "authorization_servers": [issuer()],
        "bearer_methods_supported": ["header"],
        "scopes_supported": [SCOPE],
        "resource_name": "GammaRips MCP",
        "resource_documentation": "https://gammarips.com/developers",
        "resource_policy_uri": "https://gammarips.com/terms",
    }


def www_authenticate(base: str, token_present: bool) -> str:
    parts = [
        'Bearer realm="gammarips-mcp"',
        f'resource_metadata="{base}/.well-known/oauth-protected-resource{PRO_PATH}"',
        f'scope="{SCOPE}"',
    ]
    if token_present:
        parts.insert(1, 'error="invalid_token"')
        parts.insert(
            2,
            'error_description="The access token or API key is missing, expired, or not valid for this server"',
        )
    return ", ".join(parts)


async def protected_resource_metadata(request: Request) -> Response:
    if not oauth_enabled():
        return JSONResponse({"error": "not_found"}, status_code=404)
    base = _base_url(request)
    # Path-based form: /.well-known/oauth-protected-resource/pro -> resource base/pro
    suffix = request.path_params.get("suffix", "") if hasattr(request, "path_params") else ""
    path = ""
    if suffix:
        candidate = "/" + suffix.strip("/")
        if candidate not in RESOURCE_PATHS:
            return JSONResponse({"error": "not_found"}, status_code=404)
        path = candidate
    return JSONResponse(
        protected_resource_metadata_doc(base, path),
        headers={"Cache-Control": "public, max-age=300", "Access-Control-Allow-Origin": "*"},
    )


_as_meta_cache: dict[str, Any] = {"at": 0.0, "doc": None, "last_attempt": 0.0}
_as_meta_lock = threading.Lock()


def _fetch_as_metadata() -> dict | None:
    with _as_meta_lock:
        now = time.monotonic()
        if _as_meta_cache["doc"] is not None and now - _as_meta_cache["at"] < _AS_META_TTL:
            return _as_meta_cache["doc"]
        # Same cooldown discipline as the JWKS cache: while the issuer is
        # unreachable, at most one outbound attempt per minute.
        if now - _as_meta_cache["last_attempt"] < _JWKS_REFETCH_COOLDOWN:
            return _as_meta_cache["doc"]
        _as_meta_cache["last_attempt"] = now
        try:
            resp = httpx.get(
                f"{issuer()}/.well-known/oauth-authorization-server",
                timeout=_JWKS_TIMEOUT,
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            doc = resp.json()
            if isinstance(doc, dict) and doc.get("issuer") == issuer():
                _as_meta_cache["doc"] = doc
                _as_meta_cache["at"] = now
                return doc
            logger.warning("oauth: AS metadata issuer mismatch; not served")
        except Exception as e:  # noqa: BLE001
            logger.warning("oauth: AS metadata fetch failed (%s)", e)
        return _as_meta_cache["doc"]


def set_as_metadata_for_tests(doc: dict | None) -> None:
    with _as_meta_lock:
        _as_meta_cache["doc"] = doc
        _as_meta_cache["at"] = time.monotonic() if doc else 0.0
        # A None install also arms the cooldown so the test does not hit the network.
        _as_meta_cache["last_attempt"] = time.monotonic()


async def authorization_server_metadata(request: Request) -> Response:
    """Pass-through of the issuer's RFC 8414 document for clients that only
    probe the MCP host (pre-2025-06-18 discovery). The authoritative copy is
    on the issuer; this is a cached mirror, never a second source of truth."""
    if not oauth_enabled():
        return JSONResponse({"error": "not_found"}, status_code=404)
    doc = _fetch_as_metadata()
    if doc is None:
        return JSONResponse({"error": "temporarily_unavailable"}, status_code=503)
    return JSONResponse(
        doc, headers={"Cache-Control": "public, max-age=300", "Access-Control-Allow-Origin": "*"}
    )


# --- the /pro gateway ------------------------------------------------------


class ProEndpointMiddleware:
    """Pure ASGI. For `/pro`: require a verified credential (API key or JWT of
    ANY tier — the tool-level gate still decides pro vs anon), else 401 with
    the discovery challenge. On success rewrite the path to `/mcp` so the one
    Streamable HTTP transport serves both endpoints, and stash the identity so
    the access gate reuses it. Every other path passes through untouched."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or not oauth_enabled():
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        if path.rstrip("/") != PRO_PATH:
            return await self.app(scope, receive, send)

        # Late import: utils.auth imports this module.
        from utils.auth import _extract_token, resolve_identity

        headers = Headers(scope=scope)
        identity = resolve_identity(headers)
        if identity.client_class == "none":
            request = Request(scope)
            base = _base_url(request)
            token_present = bool(_extract_token(headers))
            body = {
                "error": "invalid_token" if token_present else "unauthorized",
                "error_description": (
                    "This endpoint requires a valid credential. Chat clients: "
                    "connect to this URL and complete the sign-in it offers "
                    "(OAuth 2.1). Agents that can send headers: use an API key or "
                    "a machine-client token as 'Authorization: Bearer ...'. "
                    "Free, anonymous access is at /mcp."
                ),
                "resource_metadata": f"{base}/.well-known/oauth-protected-resource{PRO_PATH}",
                "developers_url": "https://gammarips.com/developers",
            }
            resp = JSONResponse(
                body,
                status_code=401,
                headers={
                    "WWW-Authenticate": www_authenticate(base, token_present),
                    "Cache-Control": "no-store",
                },
            )
            return await resp(scope, receive, send)

        scope["path"] = MCP_PATH
        scope["raw_path"] = MCP_PATH.encode()
        scope[SCOPE_IDENTITY_KEY] = identity
        scope[SCOPE_ENDPOINT_KEY] = "pro"
        return await self.app(scope, receive, send)
