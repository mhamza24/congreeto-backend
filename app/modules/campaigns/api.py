# app/modules/campaigns/api.py
"""
Campaign CRUD endpoints — all tenant-scoped and nested under chatbots.

  POST   /{tenant_public_id}/chatbots/{chatbot_id}/campaigns
  GET    /{tenant_public_id}/chatbots/{chatbot_id}/campaigns
  GET    /{tenant_public_id}/chatbots/{chatbot_id}/campaigns/{campaign_id}
  PATCH  /{tenant_public_id}/chatbots/{chatbot_id}/campaigns/{campaign_id}
  DELETE /{tenant_public_id}/chatbots/{chatbot_id}/campaigns/{campaign_id}
  POST   /{tenant_public_id}/chatbots/{chatbot_id}/campaigns/{campaign_id}/status
"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.core.database import get_db
from app.core.pagination import CursorPage
from app.core.response import ApiResponse
from app.dependencies.tenant import TenantContext, get_tenant_context, require_write

from . import schemas, service

settings = get_settings()

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Campaigns"])

DBDep  = Annotated[AsyncSession, Depends(get_db)]
CtxDep = Annotated[TenantContext, Depends(get_tenant_context)]


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

@router.post(
    "/{tenant_public_id}/chatbots/{chatbot_id}/campaigns",
    response_model=ApiResponse[schemas.CampaignResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Create a campaign for a chatbot",
)
async def create_campaign(
    tenant_public_id: str,
    chatbot_id: str,
    payload: schemas.CampaignCreateRequest,
    db: DBDep,
    ctx: CtxDep,
    request: Request,
):
    require_write(ctx)
    result = await service.create_campaign(
        db,
        tenant_id=ctx.tenant.id,
        chatbot_public_id=chatbot_id,
        payload=payload,
        user_id=ctx.membership.user_id,
        request=request,
    )
    return ApiResponse(success=True, data=result, message="Campaign created.")


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

@router.get(
    "/{tenant_public_id}/chatbots/{chatbot_id}/campaigns",
    response_model=ApiResponse[CursorPage[schemas.CampaignResponse]],
    summary="List campaigns for a chatbot (cursor paginated)",
)
async def list_campaigns(
    tenant_public_id: str,
    chatbot_id: str,
    db: DBDep,
    ctx: CtxDep,
    page_size: int = Query(
        default=settings.CAMPAIGNS_PAGE_SIZE_DEFAULT,
        ge=1, le=settings.CAMPAIGNS_PAGE_SIZE_MAX,
        description="Items per page.",
    ),
    cursor: str | None = Query(default=None, description="Opaque cursor from previous response."),
):
    from fastapi import HTTPException

    try:
        page = await service.list_campaigns(
            db,
            tenant_id=ctx.tenant.id,
            chatbot_public_id=chatbot_id,
            page_size=page_size,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return ApiResponse(success=True, message="OK", data=page)


# ---------------------------------------------------------------------------
# Get one
# ---------------------------------------------------------------------------

@router.get(
    "/{tenant_public_id}/chatbots/{chatbot_id}/campaigns/{campaign_id}",
    response_model=ApiResponse[schemas.CampaignResponse],
    summary="Get a single campaign by public_id",
)
async def get_campaign(
    tenant_public_id: str,
    chatbot_id: str,
    campaign_id: str,
    db: DBDep,
    ctx: CtxDep,
):
    result = await service.get_campaign(
        db,
        tenant_id=ctx.tenant.id,
        public_id=campaign_id,
    )
    return ApiResponse(success=True, data=result, message="OK")


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

@router.patch(
    "/{tenant_public_id}/chatbots/{chatbot_id}/campaigns/{campaign_id}",
    response_model=ApiResponse[schemas.CampaignResponse],
    summary="Partially update a campaign",
)
async def update_campaign(
    tenant_public_id: str,
    chatbot_id: str,
    campaign_id: str,
    payload: schemas.CampaignUpdateRequest,
    db: DBDep,
    ctx: CtxDep,
    request: Request,
):
    require_write(ctx)
    result = await service.update_campaign(
        db,
        tenant_id=ctx.tenant.id,
        public_id=campaign_id,
        payload=payload,
        user_id=ctx.membership.user_id,
        request=request,
    )
    return ApiResponse(success=True, data=result, message="Campaign updated.")


# ---------------------------------------------------------------------------
# Set status (activate / deactivate / draft)
# ---------------------------------------------------------------------------

@router.post(
    "/{tenant_public_id}/chatbots/{chatbot_id}/campaigns/{campaign_id}/status",
    response_model=ApiResponse[schemas.CampaignResponse],
    summary="Activate, deactivate, or reset a campaign to draft",
)
async def set_campaign_status(
    tenant_public_id: str,
    chatbot_id: str,
    campaign_id: str,
    payload: schemas.CampaignStatusRequest,
    db: DBDep,
    ctx: CtxDep,
    request: Request,
):
    require_write(ctx)
    result = await service.set_campaign_status(
        db,
        tenant_id=ctx.tenant.id,
        public_id=campaign_id,
        payload=payload,
        user_id=ctx.membership.user_id,
        request=request,
    )
    return ApiResponse(success=True, data=result, message=f"Campaign status set to '{payload.status.value}'.")


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

@router.delete(
    "/{tenant_public_id}/chatbots/{chatbot_id}/campaigns/{campaign_id}",
    response_model=ApiResponse[None],
    summary="Delete a campaign (conversations are preserved, campaign_id set to NULL)",
)
async def delete_campaign(
    tenant_public_id: str,
    chatbot_id: str,
    campaign_id: str,
    db: DBDep,
    ctx: CtxDep,
    request: Request,
):
    require_write(ctx)
    await service.delete_campaign(
        db,
        tenant_id=ctx.tenant.id,
        public_id=campaign_id,
        user_id=ctx.membership.user_id,
        request=request,
    )
    return ApiResponse(success=True, data=None, message="Campaign deleted.")
