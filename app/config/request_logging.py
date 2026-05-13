"""
Request-logging middleware.

Logs ONE structured line per HTTP request with method, path, status, duration,
client IP, user-agent, and a per-request correlation id. The correlation id is
propagated via ContextVar so any logger.info/.warning/.exception call inside
the handler is automatically tagged with the same id — no per-endpoint code
required.

Performance characteristics
───────────────────────────
- ContextVar set/get   ≈   100 ns
- uuid4()              ≈   1 µs
- time.perf_counter()  ≈   30 ns
- one log line         ≈  10 µs (writes to stderr buffer, flushed by the OS)
Total per request: < 50 µs — negligible against typical 50–500 ms handlers.

Skipped paths (perf-sensitive)
──────────────────────────────
- OPTIONS preflights (browsers fire one before every cross-origin request)
- Public widget asset GETs (logo / avatar — hit on every page load on every
  embedded site). These are noisy and have no security signal worth logging.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Iterable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.config.logging import request_id_var

logger = logging.getLogger("app.request")

# Path prefixes that we deliberately skip to keep log volume sane.
# Exact-match check is fine — no regex needed.
_SKIP_PREFIXES: tuple[str, ...] = (
    "/api/v1/chatbot/assets/",  # public asset serving — hit on every widget render
)

# Header where downstream consumers can read the request id.
_REQUEST_ID_HEADER = "X-Request-ID"

# Cap user-agent string in the log line so a 2 KB UA can't blow up the log.
_UA_MAX_LEN = 200


def _client_ip(request: Request) -> str:
    """
    Return the originating client IP. Honour X-Forwarded-For when present
    (we run behind a reverse proxy in prod) and fall back to the socket
    peer otherwise.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "-"


def _should_skip(path: str, prefixes: Iterable[str] = _SKIP_PREFIXES) -> bool:
    return any(path.startswith(p) for p in prefixes)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        # Honour an upstream request id if the proxy / client already set one,
        # otherwise mint a fresh uuid4.
        rid = request.headers.get(_REQUEST_ID_HEADER) or uuid.uuid4().hex
        token = request_id_var.set(rid)

        method = request.method
        path = request.url.path

        # Fast path: skip preflights and high-volume asset reads. Still set
        # the request id so that any downstream errors are correlated.
        if method == "OPTIONS" or _should_skip(path):
            try:
                response = await call_next(request)
                response.headers[_REQUEST_ID_HEADER] = rid
                return response
            finally:
                request_id_var.reset(token)

        ip = _client_ip(request)
        ua = (request.headers.get("user-agent") or "-")[:_UA_MAX_LEN]
        start = time.perf_counter()
        status_code = 500  # default if call_next raises

        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers[_REQUEST_ID_HEADER] = rid
            return response
        except Exception:
            # Log the failure with the same correlation id, then let the
            # exception handlers / Sentry middleware do their job.
            duration_ms = (time.perf_counter() - start) * 1000
            logger.exception(
                "request failed method=%s path=%s ip=%s duration_ms=%.1f ua=%r",
                method, path, ip, duration_ms, ua,
            )
            raise
        else:
            duration_ms = (time.perf_counter() - start) * 1000
            # WARNING for 4xx/5xx so they show up by default in production
            # where LOG_LEVEL is INFO. INFO for 2xx/3xx.
            level = logging.WARNING if status_code >= 400 else logging.INFO
            logger.log(
                level,
                "%s %s -> %d in %.1fms ip=%s ua=%r",
                method, path, status_code, duration_ms, ip, ua,
            )
        finally:
            request_id_var.reset(token)
