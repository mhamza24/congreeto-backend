import time
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from core.redis import redis

from app.config.settings import get_settings, Settings
settings = get_settings()

RATE_LIMIT = settings.RATE_LIMIT_REQUEST_COUNT      # max requests
WINDOW_SECONDS = settings.RATE_LIMIT_WINDOW_SECONDS    # per 60 seconds

class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Use IP as the key (or combine with user ID if authenticated)
        client_ip = request.client.host
        key = f"rate_limit:{client_ip}"
        now = time.time()
        window_start = now - WINDOW_SECONDS

        pipe = redis_client.pipeline()
        # Sliding window: remove old timestamps, add current, count
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

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(RATE_LIMIT)
        response.headers["X-RateLimit-Remaining"] = str(max(0, RATE_LIMIT - request_count))
        return response