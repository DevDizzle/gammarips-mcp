"""
Safety primitives shared across MCP tools.

The MCP server is publicly listed (Smithery, no auth) and consumed by paying
customers' chat agents — every tool response is effectively a public API
response. These helpers ensure that:

  1. Internal infra details (project IDs, fully-qualified table paths, GCP
     stack-trace paths) never leak in error messages.
  2. All caller-controlled `limit` / `days` / `lookback` parameters are clamped
     to bounded ranges before they reach BigQuery (cost-attack defense).
  3. Tool responses are size-bounded: every per-tool row limit is defined
     against the `MAX_RESPONSE_ROWS` convention (all clamps/LIMITs <= 200).
"""

from __future__ import annotations

import logging
import os
import re
import time
from collections import defaultdict
from threading import Lock

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


# Hard cap on rows returned by a single tool call. Every per-tool `limit`
# clamp and hard LIMIT is defined as <= this constant (convention enforced by
# code review + the smoke suite, not a runtime wrapper).
MAX_RESPONSE_ROWS = 200


class GlobalToolBucket:
    """Process-wide token bucket for a single expensive tool, independent of
    transport. The per-IP middleware only sees the stateless /rpc paths; tool
    calls arriving over Streamable HTTP or SSE would otherwise bypass the
    stricter per-tool limit. Phase 2 replaces this with per-key budgets."""

    def __init__(self, per_min: float, burst_multiplier: float = 1.5):
        self.capacity = per_min * burst_multiplier
        self.refill = per_min / 60.0  # tokens per second
        self.tokens = self.capacity
        self.last_refill = time.monotonic()
        self._lock = Lock()

    def try_consume(self) -> bool:
        with self._lock:
            now = time.monotonic()
            self.tokens = min(self.capacity, self.tokens + (now - self.last_refill) * self.refill)
            self.last_refill = now
            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return True
            return False


# Patterns we redact from any string surfaced to the caller. Order matters —
# longer / more specific patterns first.
_REDACT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Fully-qualified BQ table refs: `proj.dataset.table` (with or without backticks)
    (re.compile(r"`?[a-z][a-z0-9_-]*\.[a-z][a-z0-9_-]*\.[a-z][a-z0-9_-]*`?", re.I), "<bq-table>"),
    # GCP project IDs we explicitly know about
    (re.compile(r"profitscout-[a-z0-9]+", re.I), "<project>"),
    # Service-account email patterns
    (re.compile(r"[a-z0-9-]+@[a-z0-9-]+\.iam\.gserviceaccount\.com", re.I), "<sa-email>"),
    # Internal Google API URLs
    (re.compile(r"https?://[a-z0-9.-]*googleapis\.com\S*", re.I), "<google-api>"),
    # Cloud Run service URL pattern
    (re.compile(r"https?://[a-z0-9-]+-\d+\.[a-z]+-[a-z]+\d+\.run\.app\S*", re.I), "<run-url>"),
    # Polygon API key in URL params (defensive — shouldn't surface but cheap to add)
    (re.compile(r"apiKey=[A-Za-z0-9_-]+", re.I), "apiKey=<redacted>"),
    # Upstream market-data vendor URLs (cosmetic — key is header-borne, never in URL)
    (re.compile(r"https?://api\.polygon\.io\S*", re.I), "<market-data-api>"),
)


# Env vars whose LITERAL VALUES must never appear in any caller-visible
# string. Pattern-based redaction can't catch a bare token inside an arbitrary
# exception message (2026-07-06 incident: a malformed-header ValueError echoed
# the raw key), so the values themselves are scrubbed at redact time.
_SENSITIVE_ENV_VARS = ("POLYGON_API_KEY", "GOOGLE_API_KEY", "GOOGLE_CSE_ID")


def redact(text: str) -> str:
    """Apply the infra-detail redaction patterns to any string surfaced to a
    caller (error messages, BQ column descriptions, etc.)."""
    for var in _SENSITIVE_ENV_VARS:
        val = (os.getenv(var) or "").strip()
        if val and len(val) >= 8 and val in text:
            text = text.replace(val, f"<{var.lower()}>")
    for pattern, replacement in _REDACT_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def safe_error(exc: BaseException, op: str | None = None) -> str:
    """Render an exception for client consumption with infra details redacted.

    Args:
        exc: The exception caught in the tool body.
        op: Short verb describing what the tool was doing — surfaces in the
            client message ("query failed", "Firestore read failed", etc).

    Returns:
        A short string safe to return to a chat agent. Full traceback is logged
        server-side at WARNING for engineering triage.
    """
    op = op or "tool execution"
    logger.warning("safe_error: %s failed: %r", op, exc, exc_info=True)
    msg = redact(str(exc) or exc.__class__.__name__)
    # Truncate very long error messages — long stack-y strings are usually
    # internal-detail-heavy, not user-friendly.
    if len(msg) > 240:
        msg = msg[:240] + "..."
    return f"{op} failed: {msg}"


def clamp(value, lo: int, hi: int, default: int | None = None) -> int:
    """Coerce value to int and clamp to [lo, hi].

    Falls back to `default` (or `lo` if default is None) when the value cannot
    be coerced. Always returns a value in [lo, hi].
    """
    try:
        v = int(value) if value is not None else (default if default is not None else lo)
    except (TypeError, ValueError):
        v = default if default is not None else lo
    return max(lo, min(hi, v))


# ---------------------------------------------------------------------------
# Rate limiting middleware
# ---------------------------------------------------------------------------
#
# Token-bucket per client IP. In-memory only — fine for a single-replica
# Cloud Run service (min-instances=0, max-instances=2 with concurrency=80).
# If we ever scale to N replicas this becomes a per-replica budget which is
# acceptable for a free public MCP; cost-attack defense is the goal, not
# precision SLAs.


class _Bucket:
    __slots__ = ("tokens", "last_refill")

    def __init__(self, capacity: float):
        self.tokens = capacity
        self.last_refill = time.monotonic()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP token bucket. Different limits per route prefix."""

    def __init__(
        self,
        app,
        default_per_min: int = 60,
        web_search_per_min: int = 10,
        burst_multiplier: float = 1.5,
    ):
        super().__init__(app)
        self.default_capacity = default_per_min * burst_multiplier
        self.default_refill = default_per_min / 60.0  # tokens per second
        self.search_capacity = web_search_per_min * burst_multiplier
        self.search_refill = web_search_per_min / 60.0
        self._buckets_default: dict[str, _Bucket] = defaultdict(
            lambda: _Bucket(self.default_capacity)
        )
        self._buckets_search: dict[str, _Bucket] = defaultdict(
            lambda: _Bucket(self.search_capacity)
        )
        self._lock = Lock()
        self._requests_since_evict = 0

    # Buckets are per-IP dicts with no natural bound — an attacker spraying
    # spoofed X-Forwarded-For values could grow them without limit. Evict
    # entries idle > 10 minutes, checked every 5k requests.
    _EVICT_EVERY = 5000
    _EVICT_IDLE_SECONDS = 600.0

    def _maybe_evict(self) -> None:
        self._requests_since_evict += 1
        if self._requests_since_evict < self._EVICT_EVERY:
            return
        self._requests_since_evict = 0
        cutoff = time.monotonic() - self._EVICT_IDLE_SECONDS
        for buckets in (self._buckets_default, self._buckets_search):
            stale = [ip for ip, b in buckets.items() if b.last_refill < cutoff]
            for ip in stale:
                del buckets[ip]

    def _client_ip(self, request: Request) -> str:
        # Cloud Run terminates TLS at the LB; X-Forwarded-For carries the real
        # client IP. uvicorn was started with --proxy-headers --forwarded-allow-ips=*
        # (see Dockerfile), so request.client.host already reflects this.
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            return xff.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _consume(self, bucket: _Bucket, refill_rate: float, capacity: float) -> bool:
        now = time.monotonic()
        elapsed = now - bucket.last_refill
        bucket.tokens = min(capacity, bucket.tokens + elapsed * refill_rate)
        bucket.last_refill = now
        if bucket.tokens >= 1.0:
            bucket.tokens -= 1.0
            return True
        return False

    async def dispatch(self, request: Request, call_next):
        ip = self._client_ip(request)
        path = request.url.path

        # Tools/call requests for `web_search` get the stricter bucket. Other
        # paths (SSE handshake, tool list, RPC for non-search tools) use the
        # default bucket.
        is_search = False
        if path.endswith("/rpc") or path.endswith("/jsonrpc"):
            try:
                # Peek at body to detect web_search tool calls. Best-effort —
                # if body parse fails we just use the default bucket.
                body_bytes = await request.body()
                # Re-attach body for downstream consumers
                request._body = body_bytes  # noqa: SLF001
                if b'"web_search"' in body_bytes:
                    is_search = True
            except Exception:  # noqa: BLE001
                pass

        with self._lock:
            self._maybe_evict()
            if is_search:
                bucket = self._buckets_search[ip]
                ok = self._consume(bucket, self.search_refill, self.search_capacity)
            else:
                bucket = self._buckets_default[ip]
                ok = self._consume(bucket, self.default_refill, self.default_capacity)

        if not ok:
            logger.info(
                "rate_limit_exceeded",
                extra={"ip": ip, "path": path, "is_search": is_search},
            )
            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limit_exceeded",
                    "message": "Too many requests. Slow down and try again.",
                },
            )

        return await call_next(request)
