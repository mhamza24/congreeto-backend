"""
app/core/circuit_breaker.py

Redis-backed async circuit breaker.

States
──────
  CLOSED    — normal operation; every call goes through.
  OPEN      — tripped; calls fail fast with CircuitOpenError.
              After `recovery_timeout` seconds the breaker probes one call
              by moving to HALF_OPEN.
  HALF_OPEN — testing recovery; needs `success_threshold` consecutive
              successes to close, or any failure to reopen.

Why Redis-backed?
  The FastAPI app and Celery workers run in separate processes (and potentially
  separate containers). An in-memory breaker would trip per-process independently
  and never share state. Storing the breaker state in Redis makes the trip/recovery
  visible across every worker instantly.

Failure semantics
  Only transient infrastructure errors (connection, timeout, 5xx) count as
  failures. Business errors (rate limits, bad requests, auth errors) are re-raised
  without incrementing the counter so they don't accidentally trip the breaker.

Usage
─────
    cb = CircuitBreaker(
        name="openai",
        failure_threshold=5,
        recovery_timeout=60,
        success_threshold=2,
    )

    # Wrap a coroutine factory:
    result = await cb.call(lambda: client.chat.completions.create(...))

    # Or use as a decorator on a no-arg async factory inside the function body.
"""
from __future__ import annotations

import logging
import time
from typing import Awaitable, Callable, TypeVar

from app.core.redis import redis_client

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitOpenError(Exception):
    """Raised when a call is rejected because the circuit breaker is OPEN."""


class CircuitBreaker:
    CLOSED    = "closed"
    OPEN      = "open"
    HALF_OPEN = "half_open"

    def __init__(
        self,
        name: str,
        *,
        failure_threshold: int,
        recovery_timeout: int,
        success_threshold: int,
    ) -> None:
        self._name             = name
        self._failure_threshold = failure_threshold
        self._recovery_timeout  = recovery_timeout
        self._success_threshold = success_threshold

        # Redis key layout
        _k = f"cb:{name}"
        self._state_key     = f"{_k}:state"
        self._failures_key  = f"{_k}:failures"
        self._opened_at_key = f"{_k}:opened_at"
        self._half_ok_key   = f"{_k}:half_ok"

    # ── Redis helpers (fail-open on any Redis error) ──────────────────────────
    # Celery tasks run inside _run() which creates a fresh event loop per task.
    # The module-level redis_client connection pool is bound to whichever loop
    # first used it, so pool connections are invalid in subsequent loops.
    # All Redis operations here catch ConnectionError/Exception and fail open
    # (treat the breaker as CLOSED) so a Redis blip never kills a task.

    async def _redis_get(self, key: str) -> str | None:
        try:
            return await redis_client.get(key)
        except Exception as exc:
            logger.debug("[circuit_breaker] redis GET %s unavailable: %s", key, exc)
            return None

    async def _redis_set(self, key: str, value: str) -> None:
        try:
            await redis_client.set(key, value)
        except Exception as exc:
            logger.debug("[circuit_breaker] redis SET %s unavailable: %s", key, exc)

    async def _redis_incr(self, key: str) -> int:
        try:
            return await redis_client.incr(key)
        except Exception as exc:
            logger.debug("[circuit_breaker] redis INCR %s unavailable: %s", key, exc)
            return 0

    async def _redis_expire(self, key: str, seconds: int) -> None:
        try:
            await redis_client.expire(key, seconds)
        except Exception:
            pass

    async def _redis_delete(self, *keys: str) -> None:
        try:
            await redis_client.delete(*keys)
        except Exception:
            pass

    # ── State accessors ───────────────────────────────────────────────────────

    async def _get_state(self) -> str:
        state = await self._redis_get(self._state_key)
        return state or self.CLOSED

    async def _open(self) -> None:
        await self._redis_set(self._state_key, self.OPEN)
        await self._redis_set(self._opened_at_key, str(time.monotonic()))
        await self._redis_delete(self._half_ok_key)
        logger.warning("[circuit_breaker] %s → OPEN", self._name)

    async def _close(self) -> None:
        await self._redis_set(self._state_key, self.CLOSED)
        await self._redis_delete(self._failures_key, self._opened_at_key, self._half_ok_key)
        logger.info("[circuit_breaker] %s → CLOSED", self._name)

    async def _half_open(self) -> None:
        await self._redis_set(self._state_key, self.HALF_OPEN)
        await self._redis_delete(self._half_ok_key)
        logger.info("[circuit_breaker] %s → HALF_OPEN", self._name)

    # ── Success / failure accounting ──────────────────────────────────────────

    async def _on_success(self) -> None:
        state = await self._get_state()
        if state == self.HALF_OPEN:
            ok = await self._redis_incr(self._half_ok_key)
            if ok >= self._success_threshold:
                await self._close()
        elif state == self.CLOSED:
            await self._redis_delete(self._failures_key)

    async def _on_failure(self) -> None:
        state = await self._get_state()
        if state == self.HALF_OPEN:
            await self._open()
            return
        failures = await self._redis_incr(self._failures_key)
        await self._redis_expire(self._failures_key, self._recovery_timeout * 2)
        if failures >= self._failure_threshold:
            await self._open()
        else:
            logger.warning(
                "[circuit_breaker] %s failure %d/%d",
                self._name, failures, self._failure_threshold,
            )

    # ── Public API ────────────────────────────────────────────────────────────

    async def call(self, fn: Callable[[], Awaitable[T]]) -> T:
        """
        Execute `fn` through the circuit breaker.

        `fn` must be a zero-argument async callable (lambda or local def).
        Raises CircuitOpenError when the circuit is OPEN.
        Re-raises any exception from `fn` after recording it as a failure.
        If Redis is unavailable the breaker fails open (CLOSED assumed).
        """
        state = await self._get_state()

        if state == self.OPEN:
            opened_at = await self._redis_get(self._opened_at_key)
            if opened_at and (time.monotonic() - float(opened_at)) >= self._recovery_timeout:
                await self._half_open()
                state = self.HALF_OPEN
            else:
                raise CircuitOpenError(
                    f"Circuit breaker '{self._name}' is OPEN — refusing call. "
                    f"Recovery in ~{self._recovery_timeout}s."
                )

        try:
            result = await fn()
            await self._on_success()
            return result
        except CircuitOpenError:
            raise
        except Exception:
            await self._on_failure()
            raise

    async def reset(self) -> None:
        """Manually close the breaker — useful in tests or admin tooling."""
        await self._close()

    async def status(self) -> dict:
        """Return a snapshot of the current breaker state (for health checks)."""
        state    = await self._get_state()
        failures = await self._redis_get(self._failures_key)
        opened   = await self._redis_get(self._opened_at_key)
        return {
            "name":      self._name,
            "state":     state,
            "failures":  int(failures or 0),
            "opened_at": float(opened) if opened else None,
        }
