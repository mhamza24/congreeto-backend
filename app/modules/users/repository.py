from __future__ import annotations

import base64
import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

from pydantic import EmailStr
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.enums import UserStatus
from app.modules.models.otp import OTPVerification
from app.utils.hashing_utils import hash_identity

from sqlalchemy.dialects.postgresql import insert as pg_insert
from datetime import datetime, timezone
from .models import User
from app.config.settings import get_settings

settings = get_settings()


async def get_user_by_id(
    db: AsyncSession,
    *,
    id: int,
) -> User | None:
    """
    Returns the User object or None.
    Caller decides what a missing/present user means — repo stays dumb.
    """
    result = await db.execute(
        select(User).where(
            User.id == id,
            User.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()

async def get_user_by_public_id(
    db: AsyncSession,
    *,
    public_id: str,
) -> User | None:
    """
    Returns the User object or None.
    Caller decides what a missing/present user means — repo stays dumb.
    """
    result = await db.execute(
        select(User).where(
            User.public_id == public_id,
            User.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()

async def get_user_by_email(
    db: AsyncSession,
    *,
    email: str,
) -> User | None:
    """
    Returns the User object or None.
    Caller decides what a missing/present user means — repo stays dumb.
    """
    result = await db.execute(
        select(User).where(
            User.email == email.lower(),
            User.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()

async def create_user(
    db: AsyncSession,
    *,
    user: User,
) -> User:
    """
    Persists a fully-constructed User instance.
    Flush gets the DB-generated id/public_id back without committing.
    Commit is the service layer's responsibility.
    """
    db.add(user)
    await db.flush()
    # populates server_default fields (public_id, created_at)
    await db.refresh(user)
    return user


async def mark_email_verified_and_update_status(
    db: AsyncSession,
    *,
    user_id: int,
) -> User:
    """
    Marks email as verified and returns the updated user — no separate fetch needed.
    """
    result = await db.execute(
        update(User)
        .where(User.id == user_id)
        .values(email_verified_at=datetime.now(timezone.utc),
                status=UserStatus.ACTIVE)
        .returning(User)  # ← eliminates the extra get_user_by_id call
    )
    await db.commit()
    return result.scalar_one()

async def update_login_time_by_id(db: AsyncSession, *, user_id: int) -> None:

    # 1. Update user login time
    await db.execute(
        update(User)
        .where(User.id == user_id)
        .values(
            last_login_at=datetime.now(timezone.utc),
        )
    )
