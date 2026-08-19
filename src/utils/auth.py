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

OAuth 2.1 (2026-08-19, utils/oauth.py): a bearer that is a JWT is verified
against the gammarips.com JWKS instead of Firestore. The token's `tier` claim
(stamped by the authorization server from the live subscription) maps to the
same Identity, so tiering, metering, and the denial envelope are identical for
keys and tokens. `client_class` records which credential kind resolved.
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

from utils.oauth import (
    SCOPE_ENDPOINT_KEY,
    SCOPE_IDENTITY_KEY,
    looks_like_jwt,
    oauth_enabled,
    verify_access_token,
)

logger = logging.getLogger(__name__)

KEY_PREFIX = "gr_live_"
# UTM-tagged: these URLs ship only inside the paywall denial envelope, and the
# tag is what lets GA4 attribute pricing/account visits to MCP bounces.
PRICING_URL = "https://gammarips.com/pricing?utm_source=mcp_denial"
ACCOUNT_URL = "https://gammarips.com/account?utm_source=mcp_denial"
DEVELOPERS_URL = "https://gammarips.com/developers?utm_source=mcp_denial"
# Shown verbatim in the denial envelope. MUST match the live pricing page
# (same-day price-sync rule): change here and in the webapp together.
PRICE = "$39/month"
TRIAL = "7-day free trial"

# Rollout modes
MODE_OFF = "off"
MODE_SHADOW = "shadow"
MODE_ENFORCE = "enforce"

# TTL cache windows (seconds). Positive kept short so a Stripe lapse / abuse
# revocation propagates quickly (worst-case stale-pro window).
_POSITIVE_TTL = 120.0
_NEGATIVE_TTL = 60.0

# Hard cap on the identity cache so bogus-key spraying can't grow it without
# bound; oldest-inserted entries are dropped past the cap, plus a periodic
# expired-entry sweep.
_MAX_CACHE = 10_000
_SWEEP_EVERY = 2_000

# Only these tiers are privileged. A doc with a missing/unknown tier resolves
# to non-privileged — never infer pro from an absent field (fail-closed).
PRIVILEGED_TIERS = frozenset({"pro"})


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

# V4 free set (5 tools): the pool teaser + published-free report + methodology
# + regime + pure calendar reference. The 4 pro tools (get_signal,
# get_liquidity, query_outcomes, replay_contract) require an active key.
_DEFAULT_ANON_TOOLS = frozenset(
    {
        "get_pool",  # the curated pool (free preview / SEO funnel)
        "get_regime_context",  # regime rail
        "get_market_calendar_status",  # pure reference (status | scan_dates)
        "get_playbook",  # methodology + field dict + data-contract schema
        "get_daily_report",  # published free on the website (report | list)
    }
)


def anon_tools() -> frozenset[str]:
    override = os.getenv("ANON_TOOLS", "").strip()
    if override:
        return frozenset(t.strip() for t in override.split(",") if t.strip())
    return _DEFAULT_ANON_TOOLS


# get_pool is anon-DISCOVERABLE (the SEO/funnel teaser lives there), but only
# its `preview` view is free. The enriched / raw / features views ARE the paid
# product (the curated pool + point-in-time feature vectors), so anon callers
# are limited to view="preview"; everything richer requires an active pro key.
# This is the "free preview / pro full" tier from the ratified v4 tool map,
# enforced in the SAME gate as the rest of the paywall (transport-uniform, no
# handler-side request plumbing). Fail-closed: a missing/unparseable view
# resolves to the paid default ("enriched"), so anon must ASK for a free view.
_POOL_FREE_VIEWS = frozenset({"preview"})


def _pool_view(arguments) -> str:
    """The get_pool `view` arg, normalized. Anything not an explicit string
    view resolves to the handler default ("enriched"), a PAID view."""
    if not isinstance(arguments, dict):
        return "enriched"
    v = arguments.get("view")
    if not isinstance(v, str):
        return "enriched"
    return v.strip().lower()


def tool_allowed(tool: str, tier: str, arguments=None) -> bool:
    """Pro can call everything. Anon is limited to the funnel set, and WITHIN
    get_pool to the free preview view only (enriched/raw/features are the paid
    product). `arguments` is the tools/call arguments dict when available."""
    if tier == "pro":
        return True
    if tool not in anon_tools():
        return False
    if tool == "get_pool":
        return _pool_view(arguments) in _POOL_FREE_VIEWS
    return True


# --- identity resolution ---------------------------------------------------


@dataclass(frozen=True)
class Identity:
    tier: str  # "anon" | "pro"
    uid: str | None
    key_prefix: str | None  # first 12 chars of the key, for logs (never full)
    reason: str  # ok | no_key | bad_format | not_found | revoked | lookup_error | jwt_*
    # Which credential VERIFIED: none | api_key | oauth_user | oauth_machine.
    # "none" means no valid credential (anon by absence); a valid credential
    # with a free tier is still a real client class (the /pro gate admits it,
    # the tool gate denies pro tools with the upgrade envelope).
    client_class: str = "none"
    client_id: str | None = None  # OAuth client_id, for the meter


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
_cache_puts = 0


def _cache_get(key_hash: str) -> Identity | None:
    with _cache_lock:
        hit = _cache.get(key_hash)
        if hit and hit[1] > time.monotonic():
            return hit[0]
        if hit:
            _cache.pop(key_hash, None)
    return None


def _sweep_locked() -> None:
    now = time.monotonic()
    for k in [k for k, (_, exp) in _cache.items() if exp <= now]:
        _cache.pop(k, None)
    # Hard cap backstop: if still over, drop arbitrary entries (they just
    # re-resolve on next use — no correctness impact).
    while len(_cache) > _MAX_CACHE:
        _cache.pop(next(iter(_cache)), None)


def _cache_put(key_hash: str, identity: Identity, ttl: float) -> None:
    global _cache_puts
    with _cache_lock:
        _cache[key_hash] = (identity, time.monotonic() + ttl)
        _cache_puts += 1
        if _cache_puts % _SWEEP_EVERY == 0 or len(_cache) > _MAX_CACHE:
            _sweep_locked()


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
        if oauth_enabled() and looks_like_jwt(token):
            return _resolve_jwt(token)
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

    # Fail-closed on privilege: only an EXPLICIT privileged tier grants pro.
    # A missing/unknown tier on an otherwise-active doc resolves to anon so a
    # webapp write bug can never hand out free upgrades.
    raw_tier = str(doc.get("tier", "")).strip().lower()
    tier = raw_tier if raw_tier in PRIVILEGED_TIERS else "anon"
    identity = Identity(
        tier=tier,
        uid=doc.get("uid"),
        key_prefix=prefix,
        reason="ok" if tier != "anon" else "tier_not_privileged",
        client_class="api_key",
    )
    _cache_put(key_hash, identity, _POSITIVE_TTL)
    return identity


def _resolve_jwt(token: str) -> Identity:
    """OAuth access token -> Identity. Verification is local (RSA signature
    against the cached JWKS), so there is no cache and no Firestore read. An
    invalid token is anon with reason jwt_invalid; a valid token whose tier is
    not exactly `pro` is anon-tier but a REAL client (client_class set), which
    is what lets the free tools work through /pro while pro tools bounce with
    the upgrade envelope."""
    claims = verify_access_token(token)
    if claims is None:
        return _anon("jwt_invalid", "jwt:invalid")
    raw_tier = str(claims.get("tier", "")).strip().lower()
    tier = raw_tier if raw_tier in PRIVILEGED_TIERS else "anon"
    jti = str(claims.get("jti") or "")[:8]
    kind = "oauth_machine" if claims.get("client_kind") == "machine" else "oauth_user"
    return Identity(
        tier=tier,
        uid=claims.get("sub"),
        key_prefix=f"jwt:{jti}" if jti else "jwt:",
        reason="ok" if tier != "anon" else "jwt_tier_free",
        client_class=kind,
        client_id=str(claims.get("client_id") or "")[:128] or None,
    )


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


# --- metering --------------------------------------------------------------
#
# One structured event per tool call. Emitted as a JSON string on a stable
# prefix so a Cloud Logging sink -> BQ (`mcp_analytics`, one-time GCP setup) can
# parse it. No direct BQ writes from the service (read-only trust model intact).


def meter(identity: Identity, tool: str, decision: str, mode: str, endpoint: str = "mcp") -> None:
    try:
        event = {
            "tool": tool,
            "tier": identity.tier,
            "uid": identity.uid,
            "key_prefix": identity.key_prefix,
            "reason": identity.reason,
            "decision": decision,  # allowed | denied | shadow_would_deny
            "mode": mode,
            # Credential class + OAuth client, so the weekly denial-by-client
            # read (ChatGPT vs claude.ai vs Claude Code vs key) is one query.
            "client_class": identity.client_class,
            "client_id": identity.client_id,
            "endpoint": endpoint,  # mcp | pro
        }
        logger.info("MCP_TOOL_CALL %s", json.dumps(event, default=str))
    except Exception:  # noqa: BLE001
        pass  # metering must never affect request handling


# --- denial envelope -------------------------------------------------------


def denied_error(tool: str) -> dict:
    """JSON-RPC error object for a tool a caller isn't entitled to.

    This envelope is the entire sales pitch for a paywall bounce: the caller is
    an autonomous agent that relays it to a human operator. It must carry the
    price, the trial, what Pro unlocks, and the exact next steps, in both prose
    (message) and machine-legible form (data). Data-not-advice framing applies
    here like everywhere else.
    """
    # get_pool IS free at view="preview"; only the full pool is pro. Say so, so
    # a funnel agent knows the free entry point instead of just bouncing off.
    hint = (
        "get_pool(view='preview') is free; the full enriched / raw / features "
        "pool requires a subscription. "
        if tool == "get_pool"
        else ""
    )
    return {
        "code": -32001,
        "message": (
            hint + f"'{tool}' requires GammaRips Pro ({PRICE}, {TRIAL}). Pro unlocks "
            "the full curated overnight options-flow pool with point-in-time "
            "features, historical opportunity/outcome surfaces, liquidity "
            "checks, and contract replay. Data and tools, not advice. "
            f"Next steps: start the trial at {PRICING_URL} , then generate an "
            f"API key on your account page at {ACCOUNT_URL} (the key is shown "
            "once), and send it as an Authorization: Bearer header. If you "
            "connected through OAuth (ChatGPT, Claude, Cursor: you signed in "
            "when you added the server), no key is needed: pro access applies "
            "on the next token refresh, within one hour, or reconnect the "
            f"server. Setup docs: {DEVELOPERS_URL} . Relay this to your human "
            "operator."
        ),
        "data": {
            "code": "subscription_required",
            "tool": tool,
            "required_tier": "pro",
            "price": PRICE,
            "trial": TRIAL,
            "includes": [
                "full curated pool (enriched / raw / features views)",
                "historical opportunity and outcome surfaces (query_outcomes)",
                "per-contract liquidity checks (get_liquidity)",
                "contract replay (replay_contract)",
                "per-contract signal detail (get_signal)",
            ],
            "next_steps": [
                f"Subscribe ({TRIAL}) at {PRICING_URL}",
                f"API-key clients: generate a key at {ACCOUNT_URL} (shown once) and send it as 'Authorization: Bearer gr_live_...'",
                "OAuth clients (signed in when you added the server): no key; pro applies on the next token refresh (within 1 hour) or on reconnect",
            ],
            "pricing_url": PRICING_URL,
            "account_url": ACCOUNT_URL,
            "developers_url": DEVELOPERS_URL,
        },
    }


# --- middleware ------------------------------------------------------------


async def _extract_tool_calls(request: Request) -> list[tuple[str, object, dict]]:
    """Return every JSON-RPC `tools/call` in the body as (tool_name, id, args).
    Handles BOTH a single object and a batch (array) — a batched pro call must
    not slip past the gate. `args` is needed for arg-level tiering (get_pool's
    free preview vs paid full views). Body is cached back onto the request so
    downstream handlers can re-read it. Returns [] for non-tool / unparseable
    bodies."""
    try:
        body = await request.body()
        request._body = body  # noqa: SLF001 — re-attach for downstream readers
        if not body:
            return []
        payload = json.loads(body)
    except Exception:  # noqa: BLE001
        return []
    items = payload if isinstance(payload, list) else [payload]
    calls: list[tuple[str, object, dict]] = []
    for it in items:
        if isinstance(it, dict) and it.get("method") == "tools/call":
            params = it.get("params") or {}
            name = params.get("name")
            if name:
                args = params.get("arguments")
                calls.append((name, it.get("id"), args if isinstance(args, dict) else {}))
    return calls


class AccessGateMiddleware(BaseHTTPMiddleware):
    """Resolves identity, gates every `tools/call` (single OR batched) by tier,
    and meters each. Runs on all transports (`/mcp`, `/sse` + `/messages`,
    `/rpc`, `/jsonrpc`) because it inspects the JSON-RPC body, not the
    transport. Identity is resolved ONLY when a tool call is present, so
    discovery/SSE-poll traffic never triggers a Firestore lookup."""

    async def dispatch(self, request: Request, call_next):
        mode = get_auth_mode()
        if mode == MODE_OFF:
            return await call_next(request)

        calls = await _extract_tool_calls(request)
        if not calls:
            return await call_next(request)

        # The /pro gateway (utils.oauth.ProEndpointMiddleware) already resolved
        # and verified the credential for that endpoint; reuse it instead of
        # verifying the same token twice.
        identity = request.scope.get(SCOPE_IDENTITY_KEY) or resolve_identity(request.headers)
        endpoint = request.scope.get(SCOPE_ENDPOINT_KEY, "mcp")
        request.state.identity = identity  # available downstream / to loggers

        denied_tool: str | None = None
        denied_id: object = None
        for name, call_id, arguments in calls:
            allowed = tool_allowed(name, identity.tier, arguments)
            if allowed:
                decision = "allowed"
            elif mode == MODE_SHADOW:
                decision = "shadow_would_deny"
            else:
                decision = "denied"
            meter(identity, name, decision, mode, endpoint)
            if not allowed and denied_tool is None:
                denied_tool, denied_id = name, call_id

        if denied_tool is not None and mode == MODE_ENFORCE:
            # Single call: echo its id. Batch: id of the first denied element.
            return JSONResponse(
                status_code=200,
                content={"jsonrpc": "2.0", "id": denied_id, "error": denied_error(denied_tool)},
            )

        return await call_next(request)


def identity_as_dict(identity: Identity) -> dict:
    return asdict(identity)
