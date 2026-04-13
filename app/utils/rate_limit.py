import math
from datetime import timedelta

from app.core.exceptions import RateLimitError
from app.core.redis import redis_client  # your existing redis instance
from app.config.settings import get_settings
settings = get_settings()

OTP_RESEND_LIMITS = {
    1: 0,    # 1st request  — no wait
    2: 60,   # 2nd request  — wait 1 min
    3: 300,  # 3rd request  — wait 5 mins
    4: 900,  # 4th request  — wait 15 mins
    5: 3600, # 5th request  — wait 1 hour
}
MAX_OTP_ATTEMPTS   = settings.OTP_MAX_ATTEMPTS
LOCKOUT_SECONDS    = settings.OTP_LOCKOUT_SECONDS  


def _otp_rate_key(user_id: int) -> str:
    return f"otp_resend:count:{user_id}"

def _otp_lockout_key(user_id: int) -> str:
    return f"otp_resend:lockout:{user_id}"

def _otp_cooldown_key(user_id: int) -> str:
    return f"otp_resend:cooldown:{user_id}"


async def check_otp_rate_limit(user_id: int) -> None:
    """
    Raises RateLimitError if user is locked out or in cooldown.
    """
    # 1. Check hard lockout
    locked = await redis_client.get(_otp_lockout_key(user_id))
    if locked:
        ttl = await redis_client.ttl(_otp_lockout_key(user_id))
        hours = math.ceil(ttl / 3600)
        raise RateLimitError(
            f"Too many OTP requests. Try again in {hours} hour(s)."
        )

    # 2. Check cooldown
    cooldown = await redis_client.get(_otp_cooldown_key(user_id))
    if cooldown:
        ttl = await redis_client.ttl(_otp_cooldown_key(user_id))
        raise RateLimitError(
            f"Please wait {ttl} second(s) before requesting another OTP."
        )


async def record_otp_request(user_id: int) -> int:
    """
    Increments request count and sets appropriate cooldown.
    Returns current attempt number.
    """
    count_key = _otp_rate_key(user_id)

    # Increment count — expires in 24h
    count = await redis_client.incr(count_key)
    if count == 1:
        await redis_client.expire(count_key, LOCKOUT_SECONDS)

    # Hard lockout after max attempts
    if count > MAX_OTP_ATTEMPTS:
        await redis_client.setex(
            _otp_lockout_key(user_id),
            LOCKOUT_SECONDS,
            "locked",
        )
        raise RateLimitError(
            "Too many OTP requests. Your account is locked for 24 hours."
        )

    # Set exponential cooldown for next request
    wait_seconds = OTP_RESEND_LIMITS.get(count, 3600)
    if wait_seconds > 0:
        await redis_client.setex(
            _otp_cooldown_key(user_id),
            wait_seconds,
            "cooldown",
        )

    return count


# ── Login OTP lockout (separate namespace from resend rate-limit) ─────────────

def _login_otp_lockout_key(user_id: int) -> str:
    return f"login_otp:lockout:{user_id}"


async def check_login_otp_lockout(user_id: int) -> None:
    """
    Raises RateLimitError if the user is locked out from login OTP attempts.
    Call at the start of verify_login_otp before any DB work.
    """
    locked = await redis_client.get(_login_otp_lockout_key(user_id))
    if locked:
        ttl = await redis_client.ttl(_login_otp_lockout_key(user_id))
        hours = math.ceil(max(ttl, 0) / 3600)
        raise RateLimitError(
            f"Too many failed attempts. Try again in {hours} hour(s)."
        )


async def set_login_otp_lockout(user_id: int) -> None:
    """
    Sets a 24-hour hard lockout after OTP attempts are exhausted.
    Call when remaining OTP attempts hit zero.
    """
    await redis_client.setex(
        _login_otp_lockout_key(user_id),
        LOCKOUT_SECONDS,
        "locked",
    )


# ── Per-account login failure rate limiting ───────────────────────────────────

LOGIN_FAILURE_MAX    = 10   # max consecutive failures before lockout
LOGIN_FAILURE_WINDOW = 900  # 15-minute sliding window
LOGIN_FAILURE_LOCKOUT = 1800  # 30-minute lockout after max failures


def _login_failure_key(user_id: int) -> str:
    return f"login:failures:{user_id}"

def _login_failure_lockout_key(user_id: int) -> str:
    return f"login:lockout:{user_id}"


async def check_login_failure_lockout(user_id: int) -> None:
    """
    Raises RateLimitError if the account is locked out due to too many
    consecutive password failures.  Call before verifying the password.
    """
    locked = await redis_client.get(_login_failure_lockout_key(user_id))
    if locked:
        ttl = await redis_client.ttl(_login_failure_lockout_key(user_id))
        minutes = math.ceil(max(ttl, 0) / 60)
        raise RateLimitError(
            f"Too many failed login attempts. Try again in {minutes} minute(s)."
        )


async def record_login_failure(user_id: int) -> None:
    """
    Increments the failure counter for the account.  Triggers a lockout
    once LOGIN_FAILURE_MAX is reached.
    """
    key = _login_failure_key(user_id)
    count = await redis_client.incr(key)
    if count == 1:
        await redis_client.expire(key, LOGIN_FAILURE_WINDOW)

    if count >= LOGIN_FAILURE_MAX:
        await redis_client.setex(
            _login_failure_lockout_key(user_id),
            LOGIN_FAILURE_LOCKOUT,
            "locked",
        )
        await redis_client.delete(key)


async def clear_login_failures(user_id: int) -> None:
    """Reset failure counter on a successful login."""
    await redis_client.delete(_login_failure_key(user_id))