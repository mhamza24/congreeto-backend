from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import jwt
from pydantic import ValidationError, json

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
    """Builds the JWT subject dict from a User model instance."""

    is_verified = user.email_verified_at is not None

    return {
        "id":             int(user.id),
        "email":          user.email,
        "public_id":      str(user.public_id),
        "first_name":     user.first_name,
        "last_name":      user.last_name,
        "status":         user.status.value if hasattr(user.status, "value") else user.status,
        "avatar_url":     user.avatar_url,
        "email_verified": is_verified,
        "is_superadmin":  user.is_superadmin,
        "last_login":     user.last_login_at.isoformat() if user.last_login_at else None,
        "created_at":     user.created_at.isoformat(),
    }
