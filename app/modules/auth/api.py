"""
router.py — FastAPI route definitions for the chat module.

Conventions
───────────
- Routes only handle HTTP concerns: request parsing, response shaping, HTTP
  status codes. No business logic lives here.
- Business logic exceptions (ValueError) map to 404; unexpected exceptions
  map to 500. A proper exception handler is registered on the app in main.py
  (see below), so individual try/except blocks are not needed per route.
- tenant_id is injected via dependency (auth token, header, etc.).
  Hardcoded "veloce" default is kept only while auth is not wired up.
- GET /all uses Query params (not a request body) — correct REST semantics.
"""

from __future__ import annotations

import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
import sentry_sdk
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import ApiResponse
from . import schemas,service
from app.modules.chat.models import ConversationStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Auth"])

DBDep = Annotated[AsyncSession, Depends(get_db)]


@router.post(
    "/signup",
    response_model=ApiResponse[schemas.SignupResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Create a new user account and send a welcome and OTP verification email",
)
async def signup_endpoint(
    payload: schemas.SignupRequest,
    db: DBDep,
) -> ApiResponse[schemas.SignupResponse]:
    try:
        reply = await service.create_user(
            db,
            payload=payload,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception:
        logger.exception("Unexpected error in user signup")
        sentry_sdk.capture_exception(Exception)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not process your request. Please try again later.",
        )

    return ApiResponse(
        success=True,
        message="Message processed successfully.",
        data=reply,
    )
