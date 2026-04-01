from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import jwt
from pydantic import ValidationError

from app.config.settings import get_settings
from app.modules.auth.schemas import TokenPayload
from app.modules.users.models import User

settings = get_settings()

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
    )
    print("raw", raw)
    try:
        return TokenPayload(**raw)
    except ValidationError as exc:
        print("Validation error while decoding token:", exc)
        raise jwt.InvalidTokenError("Malformed token payload") from exc


def get_subject_from_token(token: str) -> dict[str, Any]:
    """Convenience helper — returns just the subject dict."""
    return decode_token(token).sub


def get_token_subject(user: User) -> dict[str, Any]:
    """Builds the JWT subject dict from a User model instance."""
    return {
        "id":             int(user.id),                    # ensure plain int
        "email":          user.email,
        "public_id":      str(user.public_id),             # UUID → str
        "first_name":     user.first_name,
        "last_name":      user.last_name,
        # handle Enum
        "status":         user.status.value if hasattr(user.status, "value") else user.status,
        "avatar_url":     user.avatar_url,
        "email_verified": user.email_verified_at is not None,          # bool, not isoformat
        "created_at":     user.created_at.isoformat(),
    }
