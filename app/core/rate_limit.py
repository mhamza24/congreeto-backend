from app.core.redis import redis_client
import time

async def rate_limit(key: str, limit: int = 5, window: int = 60):
    current = await redis_client.get(key)

    if current and int(current) >= limit:
        return False

    pipe = redis_client.pipeline()
    pipe.incr(key)
    pipe.expire(key, window)
    await pipe.execute()

    return True
