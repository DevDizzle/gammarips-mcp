"""
Safety primitives shared across MCP tools.

The MCP server is publicly listed (Smithery, no auth) and consumed by paying
customers' chat agents — every tool response is effectively a public API
response. These helpers ensure that:

  1. Internal infra details (project IDs, fully-qualified table paths, GCP
     stack-trace paths) never leak in error messages.
  2. All caller-controlled `limit` / `days` / `lookback` parameters are clamped
     to bounded ranges before they reach BigQuery (cost-attack defense).
  3. Tool responses are size-bounded (`MAX_RESPONSE_ROWS`) regardless of any
     individual tool's clamp logic.
"""

from __future__ import annotations

import logging
import re
import time
from collections import defaultdict
from threading import Lock

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


# Hard global cap on rows returned to a single tool call. Per-tool clamps
# should be tighter than this; this is the last-resort backstop.
MAX_RESPONSE_ROWS = 200


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
)


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
    msg = str(exc) or exc.__class__.__name__
    for pattern, replacement in _REDACT_PATTERNS:
        msg = pattern.sub(replacement, msg)
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
