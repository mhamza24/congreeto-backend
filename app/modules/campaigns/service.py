# app/modules/campaigns/service.py
"""
Business logic for campaign CRUD.
All functions accept (db, *, ...) and return Pydantic schemas.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_base import _new_public_id
from app.modules.audit import repository as audit
from app.modules.billing import repository as billing_repo
from app.modules.chatbot import repository as chatbot_repo

from . import repository as repo
from . import schemas, tasks

logger = logging.getLogger(__name__)


# =============================================================================
# QUOTA HELPER
# =============================================================================

async def _check_campaign_quota(db: AsyncSession, *, tenant_id: int) -> None:
    """
    Raises HTTP 402 if the tenant has reached their plan's max_campaigns limit.
    Same pattern as chatbot quota check in chatbot/service.py.
    """
    sub = await billing_repo.get_active_subscription(db, tenant_id=tenant_id)
    if sub and sub.plan:
        max_campaigns = sub.plan.get_limit("max_campaigns")
        if max_campaigns > 0:
            current = await repo.count_campaigns_for_tenant(db, tenant_id=tenant_id)
            if current >= max_campaigns:
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail=(
                        f"Campaign limit reached ({current}/{max_campaigns}). "
                        "Upgrade your plan to create more campaigns."
                    ),
                )


# =============================================================================
# CRUD
# =============================================================================

async def create_campaign(
    db: AsyncSession,
    *,
    tenant_id: int,
    chatbot_public_id: str,
    payload: schemas.CampaignCreateRequest,
    user_id: Optional[int] = None,
    request=None,
) -> schemas.CampaignResponse:
    # ── 1. Quota check ───────────────────────────────────────────────────────
    await _check_campaign_quota(db, tenant_id=tenant_id)

    # ── 2. Resolve chatbot — must belong to this tenant (cross-tenant guard) ─
    chatbot = await chatbot_repo.get_chatbot_by_public_id(
        db, tenant_id=tenant_id, public_id=chatbot_public_id
    )
    if chatbot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chatbot not found.",
        )

    # ── 3. Default campaign guard — warn if another active default exists ─────
    if payload.is_default and payload.url_patterns == []:
        existing_defaults = await repo.count_default_campaigns_for_chatbot(
            db, chatbot_config_id=chatbot.id
        )
        if existing_defaults > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "This chatbot already has an active default campaign. "
                    "Deactivate or remove the existing default before creating a new one."
                ),
            )

    # ── 4. Persist ────────────────────────────────────────────────────────────
    campaign = await repo.create_campaign(
        db,
        tenant_id=tenant_id,
        chatbot_config_id=chatbot.id,
        name=payload.name,
        description=payload.description,
        url_patterns=payload.url_patterns,
        is_default=payload.is_default,
        sort_order=payload.sort_order,
        welcome_message=payload.welcome_message,
        prompt_overlay=payload.prompt_overlay,
        public_id=_new_public_id(),
    )

    await audit.write(
        db,
        entity_type="campaigns",
        action=audit.CREATE,
        tenant_id=tenant_id,
        user_id=user_id,
        entity_id=campaign.id,
        diff={"after": {"name": campaign.name, "chatbot_config_id": chatbot.id}},
        request=request,
    )

    await db.commit()
    await db.refresh(campaign)

    # ── 5. Enqueue background prompt generation ───────────────────────────────
    tasks.generate_campaign_prompt.delay(campaign.public_id, tenant_id)

    return _to_response(campaign, chatbot_public_id=chatbot_public_id)


async def get_campaign(
    db: AsyncSession,
    *,
    tenant_id: int,
    public_id: str,
) -> schemas.CampaignResponse:
    campaign = await repo.get_campaign_by_public_id(
        db, tenant_id=tenant_id, public_id=public_id
    )
    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found.")

    # Fetch chatbot public_id for the response
    chatbot = await chatbot_repo.get_chatbot_by_id(
        db, tenant_id=tenant_id, chatbot_id=campaign.chatbot_config_id
    )
    chatbot_public_id = chatbot.public_id if chatbot else ""
    return _to_response(campaign, chatbot_public_id=chatbot_public_id)


async def list_campaigns(
    db: AsyncSession,
    *,
    tenant_id: int,
    chatbot_public_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[schemas.CampaignResponse], int]:
    chatbot_config_id: Optional[int] = None
    if chatbot_public_id:
        chatbot = await chatbot_repo.get_chatbot_by_public_id(
            db, tenant_id=tenant_id, public_id=chatbot_public_id
        )
        if chatbot is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chatbot not found.")
        chatbot_config_id = chatbot.id

    campaigns, total = await repo.list_campaigns(
        db, tenant_id=tenant_id, chatbot_config_id=chatbot_config_id,
        limit=limit, offset=offset,
    )

    # Build chatbot_public_id map to avoid N+1
    chatbot_id_map: dict[int, str] = {}
    for c in campaigns:
        if c.chatbot_config_id not in chatbot_id_map:
            cb = await chatbot_repo.get_chatbot_by_id(
                db, tenant_id=tenant_id, chatbot_id=c.chatbot_config_id
            )
            chatbot_id_map[c.chatbot_config_id] = cb.public_id if cb else ""

    items = [
        _to_response(c, chatbot_public_id=chatbot_id_map.get(c.chatbot_config_id, ""))
        for c in campaigns
    ]
    return items, total


async def update_campaign(
    db: AsyncSession,
    *,
    tenant_id: int,
    public_id: str,
    payload: schemas.CampaignUpdateRequest,
    user_id: Optional[int] = None,
    request=None,
) -> schemas.CampaignResponse:
    # Collect only the fields that were explicitly set
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields provided for update.",
        )

    # If caller is setting is_default=True, check for conflicts
    if updates.get("is_default") is True:
        existing = await repo.get_campaign_by_public_id(
            db, tenant_id=tenant_id, public_id=public_id
        )
        if existing:
            existing_defaults = await repo.count_default_campaigns_for_chatbot(
                db,
                chatbot_config_id=existing.chatbot_config_id,
                exclude_public_id=public_id,
            )
            if existing_defaults > 0:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Another active default campaign already exists for this chatbot.",
                )

    campaign = await repo.update_campaign(
        db, tenant_id=tenant_id, public_id=public_id, **updates
    )
    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found.")

    await audit.write(
        db,
        entity_type="campaigns",
        action=audit.UPDATE,
        tenant_id=tenant_id,
        user_id=user_id,
        entity_id=campaign.id,
        diff={"after": updates},
        request=request,
    )
    await db.commit()
    await db.refresh(campaign)

    # Re-generate prompt only when content-relevant fields changed
    _PROMPT_FIELDS = {"name", "description", "url_patterns", "welcome_message", "prompt_overlay"}
    if updates.keys() & _PROMPT_FIELDS:
        tasks.generate_campaign_prompt.delay(campaign.public_id, tenant_id)

    chatbot = await chatbot_repo.get_chatbot_by_id(
        db, tenant_id=tenant_id, chatbot_id=campaign.chatbot_config_id
    )
    return _to_response(campaign, chatbot_public_id=chatbot.public_id if chatbot else "")


async def set_campaign_status(
    db: AsyncSession,
    *,
    tenant_id: int,
    public_id: str,
    payload: schemas.CampaignStatusRequest,
    user_id: Optional[int] = None,
    request=None,
) -> schemas.CampaignResponse:
    campaign = await repo.set_campaign_status(
        db,
        tenant_id=tenant_id,
        public_id=public_id,
        status=payload.status,
    )
    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found.")

    await audit.write(
        db,
        entity_type="campaigns",
        action=audit.UPDATE,
        tenant_id=tenant_id,
        user_id=user_id,
        entity_id=campaign.id,
        diff={"after": {"status": payload.status.value}},
        request=request,
    )
    await db.commit()
    await db.refresh(campaign)

    chatbot = await chatbot_repo.get_chatbot_by_id(
        db, tenant_id=tenant_id, chatbot_id=campaign.chatbot_config_id
    )
    return _to_response(campaign, chatbot_public_id=chatbot.public_id if chatbot else "")


async def delete_campaign(
    db: AsyncSession,
    *,
    tenant_id: int,
    public_id: str,
    user_id: Optional[int] = None,
    request=None,
) -> None:
    # Fetch first for audit (we lose the row after delete)
    campaign = await repo.get_campaign_by_public_id(
        db, tenant_id=tenant_id, public_id=public_id
    )
    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found.")

    campaign_id = campaign.id
    deleted = await repo.delete_campaign(db, tenant_id=tenant_id, public_id=public_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found.")

    await audit.write(
        db,
        entity_type="campaigns",
        action=audit.DELETE,
        tenant_id=tenant_id,
        user_id=user_id,
        entity_id=campaign_id,
        diff={"before": {"name": campaign.name}},
        request=request,
    )
    await db.commit()


# =============================================================================
# INTERNAL HELPER
# =============================================================================

def _to_response(campaign, *, chatbot_public_id: str) -> schemas.CampaignResponse:
    return schemas.CampaignResponse(
        public_id=campaign.public_id,
        chatbot_public_id=chatbot_public_id,
        name=campaign.name,
        description=campaign.description,
        status=campaign.status,
        url_patterns=campaign.url_patterns or [],
        is_default=campaign.is_default,
        sort_order=campaign.sort_order,
        welcome_message=campaign.welcome_message,
        prompt_overlay=campaign.prompt_overlay,
        created_at=campaign.created_at,
        updated_at=campaign.updated_at,
    )
