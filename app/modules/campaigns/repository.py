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
    page_size: int = 50,
    cursor_dt: Optional[object] = None,
    cursor_id: Optional[int] = None,
) -> List[Campaign]:
    """
    Cursor-paginated campaign list.

    Sort: created_at DESC, id DESC — newest first.
    NOTE: previous behaviour sorted by sort_order ASC then created_at DESC.
    `sort_order` still drives match prioritisation in
    `match_campaign_for_url`; it is no longer the list-display order.

    Returns one extra row when more pages exist so the caller
    (CursorPage.build) can flip has_next.
    """
    from sqlalchemy import or_

    base_filter = [Campaign.tenant_id == tenant_id]
    if chatbot_config_id is not None:
        base_filter.append(Campaign.chatbot_config_id == chatbot_config_id)

    if cursor_dt is not None and cursor_id is not None:
        base_filter.append(
            or_(
                Campaign.created_at < cursor_dt,
                and_(Campaign.created_at == cursor_dt, Campaign.id < cursor_id),
            )
        )

    rows = await db.execute(
        select(Campaign)
        .where(and_(*base_filter))
        .order_by(Campaign.created_at.desc(), Campaign.id.desc())
        .limit(page_size + 1)
    )
    return list(rows.scalars().all())


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


def match_campaigns_for_url(
    campaigns: List[Campaign],
    page_url: Optional[str],
) -> List[Campaign]:
    """
    Pure Python URL matching — no DB query.  Returns ALL matching campaigns.

    Algorithm:
    1. Among campaigns WITH url_patterns: collect every campaign whose pattern
       appears (case-insensitive substring) in page_url.  The list is already
       sorted by sort_order ASC so priority order is preserved.
    2. If no url_patterns matched, fall back to the single campaign marked
       is_default=True (catch-all).
    3. Return [] if nothing matches (base chatbot behaviour, no overlay).

    This runs on the in-memory list returned by get_active_campaigns_for_chatbot()
    so there is no extra DB round-trip.
    """
    if not campaigns:
        return []

    url_lower = (page_url or "").lower()
    matched: List[Campaign] = []

    # Step 1 — URL pattern matching (collect ALL matches, not just first)
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
                    matched.append(campaign)
                    break  # don't add same campaign twice for multiple patterns

    if matched:
        return matched

    # Step 2 — Default fallback (only when no URL-specific campaign matched)
    for campaign in campaigns:
        if campaign.is_default:
            logger.debug(
                "[campaign] Default campaign selected: %s", campaign.public_id
            )
            return [campaign]

    return []


# Keep old name as an alias so any callers outside the chat service still work.
def match_campaign_for_url(
    campaigns: List[Campaign],
    page_url: Optional[str],
) -> Optional[Campaign]:
    """Deprecated — use match_campaigns_for_url which returns all matches."""
    results = match_campaigns_for_url(campaigns, page_url)
    return results[0] if results else None
