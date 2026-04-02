# app/dependencies/user.py

from fastapi import Depends, HTTPException, status

from app.core.enums import UserStatus
from app.core.exceptions import UserStatusError
from app.modules.users.models import User
from app.dependencies.auth import get_current_user


async def get_verified_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Extends get_current_user with account status checks.
    Use on any endpoint that requires a fully active account.

    Gate order:
        1. get_current_user — token valid + user exists  (auth.py)
        2. suspended → 403
        3. inactive   → 403
        4. invited    → 403  (email not yet verified)
        5. active     → pass
    """
    if current_user.status == UserStatus.SUSPENDED:
        raise UserStatusError(
            "Your account has been suspended. Please contact support.")

    if current_user.status == UserStatus.INACTIVE:
        raise UserStatusError(
            "Your account is inactive. Please contact your administrator.")

    if current_user.status == UserStatus.INVITED:
        raise UserStatusError("Please verify your email before continuing.")

    return current_user
