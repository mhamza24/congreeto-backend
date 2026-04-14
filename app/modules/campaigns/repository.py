# app/modules/campaigns/repository.py
"""
Pure DB access — no business logic. All methods are tenant-scoped.
The service layer is the only caller.
"""
from __future__ import annotations

import logging
from typing import List, Optional, Tuple

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import CampaignStatus
from .models import Campaign

logger = logging.getLogger(__name__)


# =============================================================================
# WRITES
# =============================================================================

async def create_campaign(
    db: AsyncSession,
    *,
    tenant_id: int,
    chatbot_config_id: int,
    name: str,
    description: Optional[str],
    url_patterns: List[str],
    is_default: bool,
    sort_order: int,
    welcome_message: Optional[str],
    prompt_overlay: Optional[str],
    public_id: str,
) -> Campaign:
    campaign = Campaign(
        tenant_id=tenant_id,
        chatbot_config_id=chatbot_config_id,
        name=name,
        description=description,
        url_patterns=url_patterns,
        is_default=is_default,
        sort_order=sort_order,
        welcome_message=welcome_message,
        prompt_overlay=prompt_overlay,
        public_id=public_id,
    )
    db.add(campaign)
    await db.flush()
    return campaign


async def update_campaign(
    db: AsyncSession,
    *,
    tenant_id: int,
    public_id: str,
    **fields,
) -> Optional[Campaign]:
    """
    Partial update — only columns present in `fields` are touched.
    Returns None if not found.
    """
    result = await db.execute(
        select(Campaign).where(
            Campaign.public_id == public_id,
            Campaign.tenant_id == tenant_id,
        )
    )
    campaign = result.scalar_one_or_none()
    if campaign is None:
        return None

    for key, value in fields.items():
        if hasattr(campaign, key):
            setattr(campaign, key, value)

    await db.flush()
    return campaign


async def set_campaign_status(
    db: AsyncSession,
    *,
    tenant_id: int,
    public_id: str,
    status: CampaignStatus,
) -> Optional[Campaign]:
    result = await db.execute(
        select(Campaign).where(
            Campaign.public_id == public_id,
            Campaign.tenant_id == tenant_id,
        )
    )
    campaign = result.scalar_one_or_none()
    if campaign is None:
        return None
    campaign.status = status
    await db.flush()
    return campaign


async def delete_campaign(
    db: AsyncSession,
    *,
    tenant_id: int,
    public_id: str,
) -> bool:
    """Hard delete. Conversations keep campaign_id=NULL via ON DELETE SET NULL."""
    result = await db.execute(
        select(Campaign).where(
            Campaign.public_id == public_id,
            Campaign.tenant_id == tenant_id,
        )
    )
    campaign = result.scalar_one_or_none()
    if campaign is None:
        return False
    await db.delete(campaign)
    await db.flush()
    return True


# =============================================================================
# READS
# =============================================================================

async def get_campaign_by_public_id(
    db: AsyncSession,
    *,
    tenant_id: int,
    public_id: str,
) -> Optional[Campaign]:
    result = await db.execute(
        select(Campaign).where(
            Campaign.public_id == public_id,
            Campaign.tenant_id == tenant_id,
        )
    )
    return result.scalar_one_or_none()


async def list_campaigns(
    db: AsyncSession,
    *,
    tenant_id: int,
    chatbot_config_id: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
) -> Tuple[List[Campaign], int]:
    """
    Returns (campaigns, total_count).
    Optionally filtered to a specific chatbot.
    Ordered by sort_order ASC, then created_at DESC.
    """
    base_filter = [Campaign.tenant_id == tenant_id]
    if chatbot_config_id is not None:
        base_filter.append(Campaign.chatbot_config_id == chatbot_config_id)

    count_q = await db.execute(
        select(func.count()).select_from(Campaign).where(and_(*base_filter))
    )
    total = count_q.scalar_one()

    rows = await db.execute(
        select(Campaign)
        .where(and_(*base_filter))
        .order_by(Campaign.sort_order.asc(), Campaign.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    campaigns = list(rows.scalars().all())
    return campaigns, total


async def count_campaigns_for_tenant(
    db: AsyncSession,
    *,
    tenant_id: int,
) -> int:
    """Total campaign count for quota enforcement (all statuses)."""
    result = await db.execute(
        select(func.count())
        .select_from(Campaign)
        .where(Campaign.tenant_id == tenant_id)
    )
    return result.scalar_one()


async def count_default_campaigns_for_chatbot(
    db: AsyncSession,
    *,
    chatbot_config_id: int,
    exclude_public_id: Optional[str] = None,
) -> int:
    """
    Count active default campaigns for a chatbot.
    Used to enforce the 'at most one default per chatbot' rule at service layer.
    """
    filters = [
        Campaign.chatbot_config_id == chatbot_config_id,
        Campaign.is_default == True,
        Campaign.status == CampaignStatus.ACTIVE,
    ]
    if exclude_public_id:
        filters.append(Campaign.public_id != exclude_public_id)

    result = await db.execute(
        select(func.count()).select_from(Campaign).where(and_(*filters))
    )
    return result.scalar_one()


async def get_active_campaigns_for_chatbot(
    db: AsyncSession,
    *,
    chatbot_config_id: int,
) -> List[Campaign]:
    """
    Load all ACTIVE campaigns for a chatbot, ordered by sort_order ASC.
    Called by the chat service on every new conversation to run URL matching.
    """
    result = await db.execute(
        select(Campaign)
        .where(
            Campaign.chatbot_config_id == chatbot_config_id,
            Campaign.status == CampaignStatus.ACTIVE,
        )
        .order_by(Campaign.sort_order.asc(), Campaign.created_at.desc())
    )
    return list(result.scalars().all())


def match_campaign_for_url(
    campaigns: List[Campaign],
    page_url: Optional[str],
) -> Optional[Campaign]:
    """
    Pure Python URL matching — no DB query.

    Algorithm:
    1. Among campaigns WITH url_patterns: find those whose pattern appears
       (case-insensitive substring) in page_url. If multiple match, the one
       with the lowest sort_order wins (already sorted by the query).
    2. If nothing matches, fall back to the campaign marked is_default=True.
    3. If no default, return None (base chatbot behaviour, no overlay).

    This runs on the in-memory list returned by get_active_campaigns_for_chatbot()
    so there is no extra DB round-trip.
    """
    if not campaigns:
        return None

    url_lower = (page_url or "").lower()

    # Step 1 — URL pattern matching
    if url_lower:
        for campaign in campaigns:
            patterns = campaign.url_patterns or []
            if not patterns:
                continue
            for pattern in patterns:
                if pattern and pattern.lower() in url_lower:
                    logger.debug(
                        "[campaign] URL match: campaign=%s pattern=%r page_url=%r",
                        campaign.public_id, pattern, page_url,
                    )
                    return campaign

    # Step 2 — Default fallback
    for campaign in campaigns:
        if campaign.is_default:
            logger.debug(
                "[campaign] Default campaign selected: %s", campaign.public_id
            )
            return campaign

    return None
