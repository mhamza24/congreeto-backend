from fastapi import Depends, HTTPException, status  # ← status from fastapi, not alembic
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials  # ← add HTTPBearer
import jwt
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
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload.type != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type.",
        )

    # ── Pull whatever fields you stored in sub ────────────────────────────
    sub = payload.sub

    user = await user_repo.get_user_by_id(db, user_id=sub["id"])
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists.",
        )

    return user