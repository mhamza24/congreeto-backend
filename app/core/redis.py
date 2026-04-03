import redis.asyncio as redis
import ssl
from app.config.settings import get_settings

settings = get_settings()

# ✅ Add SSL for Heroku's rediss:// URLs
if settings.ENV in ["PRODUCTION", "STAGING"]:
    redis_client = redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        ssl_cert_reqs=None,
    )
else:
    redis_client = redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
    )
