import time
import logging
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from app.core.redis import redis_client
from app.config.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

RATE_LIMIT = settings.RATE_LIMIT_REQUEST_COUNT
WINDOW_SECONDS = settings.RATE_LIMIT_WINDOW_SECONDS


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host
        key = f"rate_limit:{client_ip}"
        now = time.time()
        window_start = now - WINDOW_SECONDS

        try:
            async with redis_client.pipeline(transaction=True) as pipe:
                pipe.zremrangebyscore(key, 0, window_start)
                pipe.zadd(key, {str(now): now})
                pipe.zcard(key)
                pipe.expire(key, WINDOW_SECONDS)
                results = await pipe.execute()

            request_count = results[2]

            if request_count > RATE_LIMIT:
                return Response(
                    content='{"detail": "Too many requests. Slow down."}',
                    status_code=429,
                    headers={
                        "Content-Type": "application/json",
                        "Retry-After": str(WINDOW_SECONDS),
                        "X-RateLimit-Limit": str(RATE_LIMIT),
                        "X-RateLimit-Remaining": "0",
                    },
                )

        except Exception as e:
            logger.warning(f"Rate limiter Redis error, allowing request (fail-open): {e}")
            return await call_next(request)

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(RATE_LIMIT)
        response.headers["X-RateLimit-Remaining"] = str(max(0, RATE_LIMIT - request_count))
        return response