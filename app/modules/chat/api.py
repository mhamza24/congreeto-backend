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
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import ApiResponse
from app.modules.chat import schemas, service
from app.modules.chat.models import ConversationStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["Chat"])


# ---------------------------------------------------------------------------
# Dependency — tenant resolution
# (replace with real auth when ready)
# ---------------------------------------------------------------------------

async def get_tenant_id() -> str:
    """
    Placeholder: extract tenant_id from JWT / API-key header.
    Replace with real auth logic — e.g.:
        token_data = await auth_barrier(request)
        return token_data.tenant_id
    """
    return "veloce"


TenantDep = Annotated[str, Depends(get_tenant_id)]
DBDep     = Annotated[AsyncSession, Depends(get_db)]


# ---------------------------------------------------------------------------
# POST /chat/  — create or continue a conversation
# ---------------------------------------------------------------------------

@router.post(
    "/",
    response_model=ApiResponse[schemas.ChatReplyResponse],
    status_code=status.HTTP_200_OK,
    summary="Send a message (creates a new conversation if no conversation_id provided)",
)
async def chat_endpoint(
    payload: schemas.ChatCreateRequest,
    db: DBDep,
) -> ApiResponse[schemas.ChatReplyResponse]:
    try:
        reply = await service.create_or_continue_chat(
            db,
            payload=payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception:
        logger.exception("Unexpected error in chat_endpoint")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not process your request. Please try again later.",
        )

    return ApiResponse(
        success=True,
        message="Message processed successfully.",
        data=reply,
    )


# ---------------------------------------------------------------------------
# GET /chat/  — list conversations (keyset paginated)
# ---------------------------------------------------------------------------

@router.get(
    "/",
    response_model=ApiResponse[schemas.PaginatedResponse[schemas.ConversationSummaryResponse]],
    status_code=status.HTTP_200_OK,
    summary="List conversations (keyset/cursor paginated)",
)
async def list_conversations_endpoint(
    db: DBDep,
    tenant_id: TenantDep,
    page_size: int  = Query(default=20, ge=1, le=100, description="Number of results per page."),
    cursor:    Optional[str] = Query(default=None, description="Pagination cursor from previous response."),
    status_filter: Optional[ConversationStatus] = Query(
        default=None,
        alias="status",
        description="Filter by conversation status.",
    ),
) -> ApiResponse[schemas.PaginatedResponse[schemas.ConversationSummaryResponse]]:
    """
    Returns conversations newest-first.

    **Pagination**
    - First page: omit `cursor`.
    - Subsequent pages: pass `meta.next_cursor` from the previous response.
    - `meta.has_next = false` means you are on the last page.

    This endpoint does **not** return messages — use `GET /chat/{id}` for that.
    """
    try:
        payload = schemas.ConversationListRequest(
            page_size=page_size,
            cursor=cursor,
            status=status_filter,
        )
        result = await service.list_conversations(
            db,
            payload=payload,
            tenant_id=tenant_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception:
        logger.exception("Unexpected error in list_conversations_endpoint")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not fetch conversations. Please try again later.",
        )

    return ApiResponse(
        success=True,
        message="Conversations fetched successfully.",
        data=result,
    )


# ---------------------------------------------------------------------------
# GET /chat/{conversation_id}  — get single conversation with messages
# ---------------------------------------------------------------------------

@router.get(
    "/{conversation_id}",
    response_model=ApiResponse[schemas.ConversationDetailResponse],
    status_code=status.HTTP_200_OK,
    summary="Get a single conversation with all messages",
)
async def get_conversation_endpoint(
    conversation_id: str,
    db: DBDep,
    tenant_id: TenantDep,
) -> ApiResponse[schemas.ConversationDetailResponse]:
    """
    Returns the conversation and **all** its messages.

    Messages are loaded with `selectinload` (2 SQL queries total, regardless
    of message count — no N+1).
    """
    try:
        detail = await service.get_conversation_detail(
            db,
            conversation_public_id=conversation_id,
            tenant_id=tenant_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception:
        logger.exception("Unexpected error in get_conversation_endpoint")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not fetch conversation. Please try again later.",
        )

    return ApiResponse(
        success=True,
        message="Conversation fetched successfully.",
        data=detail,
    )