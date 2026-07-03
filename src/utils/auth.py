"""
Phase 2 auth + tiering for the GammaRips MCP server.

Model (see docs/MCP-V3-SPEC.md §3):
  * Bearer / X-API-Key -> SHA-256 -> Firestore `mcp_api_keys/{sha256(key)}`
    -> {uid, tier, status}. The MCP server ONLY READS this collection; the
    webapp owns writes (key issuance + Stripe status sync). Plaintext keys are
    never stored — the doc id IS the hash, so lookup is a single get().
  * Per-tool tiering: an `anon` (free funnel) set; everything else is `pro`.
  * Staged rollout via env:
      REQUIRE_API_KEY=true            -> ENFORCE (deny pro tools without a key)
      AUTH_SHADOW=true (req false)    -> SHADOW  (resolve + log would-be denials,
                                                  block nothing)
      neither                        -> OFF     (pure passthrough — pre-Phase-2)
    Rollback is an env flip, no redeploy of code.

The read-only trust model is preserved: this module only READS Firestore and
emits structured log events (a Cloud Logging sink → BQ does the analytics). No
BQ/Firestore writes from the service.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from threading import Lock

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

KEY_PREFIX = "gr_live_"
PRICING_URL = "https://gammarips.com/pricing"
DEVELOPERS_URL = "https://gammarips.com/developers"

# Rollout modes
MODE_OFF = "off"
MODE_SHADOW = "shadow"
MODE_ENFORCE = "enforce"

# TTL cache windows (seconds)
_POSITIVE_TTL = 300.0
_NEGATIVE_TTL = 60.0


def get_auth_mode() -> str:
    """Resolve the rollout mode from env at call time (so an env flip on the
    running revision takes effect without a code redeploy)."""
    if os.getenv("REQUIRE_API_KEY", "false").strip().lower() == "true":
        return MODE_ENFORCE
    if os.getenv("AUTH_SHADOW", "false").strip().lower() == "true":
        return MODE_SHADOW
    return MODE_OFF


# --- tool tiers ------------------------------------------------------------
#
# ANON = the free funnel/marketing surface (teaser + published-free content +
# methodology + pure reference). Everything else is PRO. Overridable via the
# ANON_TOOLS env var (comma-separated) so the owner can move a tool between
# tiers without a code change.

_DEFAULT_ANON_TOOLS = frozenset(
    {
        "get_freemium_preview",  # the teaser
        "get_daily_report",  # published free on the website
        "get_report_list",
        "list_playbooks",  # methodology = marketing
        "get_playbook",
        "get_market_calendar_status",  # pure reference
        "get_signal_explainer",
        "get_available_dates",
    }
)


def anon_tools() -> frozenset[str]:
    override = os.getenv("ANON_TOOLS", "").strip()
    if override:
        return frozenset(t.strip() for t in override.split(",") if t.strip())
    return _DEFAULT_ANON_TOOLS


def tool_allowed(tool: str, tier: str) -> bool:
    """Pro can call everything; anon is limited to the funnel set."""
    if tier == "pro":
        return True
    return tool in anon_tools()


# --- identity resolution ---------------------------------------------------


@dataclass(frozen=True)
class Identity:
    tier: str  # "anon" | "pro"
    uid: str | None
    key_prefix: str | None  # first 12 chars of the key, for logs (never full)
    reason: str  # ok | no_key | bad_format | not_found | revoked | lookup_error


def hash_key(raw_key: str) -> str:
    """SHA-256 hex of the full raw key (prefix included). The webapp MUST hash
    identically to produce the Firestore doc id."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _extract_token(headers) -> str | None:
    auth = headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    x = headers.get("x-api-key")
    return x.strip() if x else None


# Firestore client is lazy + guarded — a missing/failed client must never crash
# the server; it degrades to "no key resolvable" (anon).
_fs_client = None
_fs_init_tried = False


def _firestore():
    global _fs_client, _fs_init_tried
    if _fs_init_tried:
        return _fs_client
    _fs_init_tried = True
    try:
        from google.cloud import firestore

        _fs_client = firestore.Client(project=os.getenv("GCP_PROJECT_ID", "profitscout-fida8"))
    except Exception as e:  # noqa: BLE001
        logger.error("auth: Firestore client init failed: %s", e)
        _fs_client = None
    return _fs_client


def _lookup_key(key_hash: str) -> dict | None:
    """Read `mcp_api_keys/{key_hash}`. Returns the doc dict or None. Injectable
    seam for tests (monkeypatch this)."""
    db = _firestore()
    if db is None:
        raise RuntimeError("firestore_unavailable")
    snap = db.collection("mcp_api_keys").document(key_hash).get()
    return snap.to_dict() if snap.exists else None


_cache: dict[str, tuple[Identity, float]] = {}
_cache_lock = Lock()


def _cache_get(key_hash: str) -> Identity | None:
    with _cache_lock:
        hit = _cache.get(key_hash)
        if hit and hit[1] > time.monotonic():
            return hit[0]
        if hit:
            _cache.pop(key_hash, None)
    return None


def _cache_put(key_hash: str, identity: Identity, ttl: float) -> None:
    with _cache_lock:
        _cache[key_hash] = (identity, time.monotonic() + ttl)


def _anon(reason: str, key_prefix: str | None = None) -> Identity:
    return Identity(tier="anon", uid=None, key_prefix=key_prefix, reason=reason)


def resolve_identity(headers) -> Identity:
    """Map request headers to an Identity. Never raises — any failure degrades
    to anon (fail-closed on privilege, fail-open on availability: an unknown or
    unverifiable key is treated as anon, so a Firestore blip can't grant pro but
    also can't 500 the request)."""
    token = _extract_token(headers)
    if not token:
        return _anon("no_key")
    if not token.startswith(KEY_PREFIX):
        return _anon("bad_format")

    prefix = token[:12]
    key_hash = hash_key(token)

    cached = _cache_get(key_hash)
    if cached is not None:
        return cached

    try:
        doc = _lookup_key(key_hash)
    except Exception as e:  # noqa: BLE001
        # Availability failure — do NOT cache, do NOT grant privilege.
        logger.warning("auth: key lookup failed (%s); treating as anon", e)
        return _anon("lookup_error", prefix)

    if not doc:
        identity = _anon("not_found", prefix)
        _cache_put(key_hash, identity, _NEGATIVE_TTL)
        return identity
    if str(doc.get("status", "")).lower() != "active":
        identity = _anon("revoked", prefix)
        _cache_put(key_hash, identity, _NEGATIVE_TTL)
        return identity

    identity = Identity(
        tier=str(doc.get("tier", "pro")).lower() or "pro",
        uid=doc.get("uid"),
        key_prefix=prefix,
        reason="ok",
    )
    _cache_put(key_hash, identity, _POSITIVE_TTL)
    return identity


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


# --- metering --------------------------------------------------------------
#
# One structured event per tool call. Emitted as a JSON string on a stable
# prefix so a Cloud Logging sink -> BQ (`mcp_analytics`, one-time GCP setup) can
# parse it. No direct BQ writes from the service (read-only trust model intact).


def meter(identity: Identity, tool: str, decision: str, mode: str) -> None:
    try:
        event = {
            "tool": tool,
            "tier": identity.tier,
            "uid": identity.uid,
            "key_prefix": identity.key_prefix,
            "reason": identity.reason,
            "decision": decision,  # allowed | denied | shadow_would_deny
            "mode": mode,
        }
        logger.info("MCP_TOOL_CALL %s", json.dumps(event, default=str))
    except Exception:  # noqa: BLE001
        pass  # metering must never affect request handling


# --- denial envelope -------------------------------------------------------


def denied_error(tool: str) -> dict:
    """JSON-RPC error object for a tool a caller isn't entitled to."""
    return {
        "code": -32001,
        "message": (
            f"'{tool}' requires a GammaRips subscription. Subscribe and generate "
            f"an API key at {PRICING_URL}, then send it as an Authorization: "
            f"Bearer header."
        ),
        "data": {
            "code": "subscription_required",
            "tool": tool,
            "required_tier": "pro",
            "pricing_url": PRICING_URL,
            "developers_url": DEVELOPERS_URL,
        },
    }


# --- middleware ------------------------------------------------------------


async def _peek_tool_call(request: Request) -> tuple[str | None, object]:
    """If the request body is a single JSON-RPC `tools/call`, return
    (tool_name, id); otherwise (None, id?). Body is cached back onto the request
    so downstream handlers can re-read it."""
    try:
        body = await request.body()
        request._body = body  # noqa: SLF001 — re-attach for downstream readers
        if not body:
            return None, None
        payload = json.loads(body)
    except Exception:  # noqa: BLE001
        return None, None
    # Batch requests (list) are not gated here — rare for tool calls; they fall
    # through to normal handling. Documented limitation.
    if isinstance(payload, dict) and payload.get("method") == "tools/call":
        params = payload.get("params") or {}
        return params.get("name"), payload.get("id")
    return None, None


class AccessGateMiddleware(BaseHTTPMiddleware):
    """Resolves identity, gates `tools/call` by tier, and meters every tool
    call. Runs on all transports (`/mcp`, `/sse` + `/messages`, `/rpc`,
    `/jsonrpc`) because it inspects the JSON-RPC body, not the transport."""

    async def dispatch(self, request: Request, call_next):
        mode = get_auth_mode()
        if mode == MODE_OFF:
            return await call_next(request)

        tool, req_id = await _peek_tool_call(request)
        identity = resolve_identity(request.headers)
        request.state.identity = identity  # available downstream / to loggers

        if tool is None:
            return await call_next(request)

        allowed = tool_allowed(tool, identity.tier)
        if allowed:
            decision = "allowed"
        elif mode == MODE_SHADOW:
            decision = "shadow_would_deny"
        else:
            decision = "denied"
        meter(identity, tool, decision, mode)

        if not allowed and mode == MODE_ENFORCE:
            return JSONResponse(
                status_code=200,
                content={"jsonrpc": "2.0", "id": req_id, "error": denied_error(tool)},
            )

        return await call_next(request)


def identity_as_dict(identity: Identity) -> dict:
    return asdict(identity)
