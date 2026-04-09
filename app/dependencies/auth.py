from fastapi import Depends, HTTPException, status  # ← status from fastapi, not alembic
from fastapi.security import (
    HTTPBearer,
    HTTPAuthorizationCredentials,
)  # ← add HTTPBearer
import jwt
from app.core.exceptions import (
    InvalidCredentialsError,
    InvalidTokenError,
    InvalidTokenTypeError,
    UserNotFoundError,
)
from app.modules.users import repository as user_repo
from app.core.database import get_db
from app.utils.jwt_utils import decode_token

bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db=Depends(get_db),
):
    token = credentials.credentials

    try:
        payload = decode_token(token)
    except Exception:
        raise InvalidTokenError()
    except jwt.PyJWTError:
        raise InvalidCredentialsError()

    if payload.type != "access":
        raise InvalidTokenTypeError()

    # ── Pull whatever fields you stored in sub ────────────────────────────
    sub = payload.sub

    user = await user_repo.get_user_by_id(db, id=sub["id"])
    if user is None:
        raise UserNotFoundError()

    return user


async def require_superadmin(
    current_user=Depends(get_current_user),
):
    if not current_user.is_superadmin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Superadmin access required.",
        )
    return current_user
