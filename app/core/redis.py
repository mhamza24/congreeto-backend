import redis.asyncio as redis
from redis.asyncio import ConnectionPool
from redis.asyncio.retry import Retry
from redis.backoff import ExponentialBackoff
from app.config.settings import get_settings

settings = get_settings()

retry = Retry(ExponentialBackoff(), 3)

if settings.ENV in ["PRODUCTION", "STAGING"]:
    pool = ConnectionPool.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        ssl_cert_reqs=None,
        max_connections=3,
        socket_keepalive=True,
        socket_connect_timeout=5,
        socket_timeout=5,
        retry=retry,
        retry_on_error=[ConnectionError, TimeoutError],
        health_check_interval=30,
    )
else:
    pool = ConnectionPool.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        max_connections=3,
        socket_keepalive=True,
        socket_connect_timeout=5,
        socket_timeout=5,
        retry=retry,
        retry_on_error=[ConnectionError, TimeoutError],
        health_check_interval=30,
    )

redis_client = redis.Redis(connection_pool=pool)