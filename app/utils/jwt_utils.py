import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import jwt
from pydantic import ValidationError, json

from app.config.settings import get_settings
from app.modules.auth.schemas import TokenPayload
from app.modules.users.models import User

settings = get_settings()

# ── Token blacklist (Redis-backed) ────────────────────────────────────────────

def _blacklist_key(jti: str) -> str:
    return f"jwt:blacklist:{jti}"


async def blacklist_token(token: str) -> None:
    """
    Adds a token to the Redis blacklist until it naturally expires.
    Call on logout or password change to invalidate previously issued tokens.
    """
    from app.core.redis import redis_client
    try:
        raw = jwt.decode(
            token,
            JWT_SECRET_KEY,
            algorithms=[JWT_ALGORITHM],
            options={"verify_sub": False},
        )
        exp = raw.get("exp")
        jti = raw.get("jti") or token[-32:]  # fall back to token suffix as identifier
        if exp:
            ttl = int(exp - datetime.now(timezone.utc).timestamp())
            if ttl > 0:
                await redis_client.setex(_blacklist_key(jti), ttl, "1")
    except Exception:
        pass  # if decode fails the token is already invalid


async def is_token_blacklisted(jti: str) -> bool:
    from app.core.redis import redis_client
    try:
        return bool(await redis_client.get(_blacklist_key(jti)))
    except Exception:
        return False  # fail-open for blacklist check (token still validated by signature)

ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES
REFRESH_TOKEN_EXPIRE_DAYS = settings.REFRESH_TOKEN_EXPIRE_DAYS
JWT_SECRET_KEY = settings.JWT_SECRET
JWT_ALGORITHM = settings.JWT_ALGORITHM

# ── Creators ─────────────────────────────────────────────────────────────────

def _create_token(
    subject: dict[str, Any],
    token_type: Literal["access", "refresh"],
    expires_delta: timedelta,
) -> str:
    expire = datetime.now(timezone.utc) + expires_delta
    payload = {
        "sub":  subject,      # entire dict embedded directly
        "type": token_type,
        "exp":  expire,
        "jti":  str(uuid.uuid4()),  # unique token ID for revocation
    }

    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

def create_access_token(subject: dict[str, Any]) -> str:
    return _create_token(
        subject=subject,
        token_type="access",
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )

def create_refresh_token(subject: dict[str, Any]) -> str:
    return _create_token(
        subject=subject,
        token_type="refresh",
        expires_delta=timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    )

# ── Verifier ──────────────────────────────────────────────────────────────────

def decode_token(token: str) -> TokenPayload:
    raw = jwt.decode(
        token,
        JWT_SECRET_KEY,
        algorithms=[JWT_ALGORITHM],
        options={"verify_sub": False},
    )
    try:
        # sub might already be a dict if PyJWT auto-parsed it
        if isinstance(raw["sub"], str):
            raw["sub"] = json.loads(raw["sub"])
        return TokenPayload(**raw)
    except json.JSONDecodeError as exc:
        raise jwt.InvalidTokenError("Bad sub format.") from exc
    except ValidationError as exc:
        raise jwt.InvalidTokenError("Malformed token payload.") from exc

def get_subject_from_token(token: str) -> dict[str, Any]:
    """Convenience helper — returns just the subject dict."""
    return decode_token(token).sub

def get_token_subject(user: User) -> dict[str, Any]:
    """Builds the JWT subject dict from a User model instance.
    Contains only auth-decision fields — no PII. Fetch profile from GET /users/me.
    """
    return {
        "id":             int(user.id),
        "public_id":      str(user.public_id),
        "status":         user.status.value if hasattr(user.status, "value") else user.status,
        "email_verified": user.email_verified_at is not None,
        "is_superadmin":  user.is_superadmin,
    }
