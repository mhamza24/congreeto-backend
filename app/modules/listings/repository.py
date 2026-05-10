from __future__ import annotations

import logging
from typing import Dict, List, Optional, Sequence

from sqlalchemy import func, select, update

logger = logging.getLogger(__name__)
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.chatbot.models import Listing


async def get_listing_by_public_id(
    db: AsyncSession, *, tenant_id: int, public_id: str
) -> Optional[Listing]:
    result = await db.execute(
        select(Listing).where(
            Listing.public_id == public_id,
            Listing.tenant_id == tenant_id,
            Listing.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def get_listing_by_external_id(
    db: AsyncSession, *, tenant_id: int, external_id: str
) -> Optional[Listing]:
    result = await db.execute(
        select(Listing).where(
            Listing.external_id == external_id,
            Listing.tenant_id == tenant_id,
            Listing.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def get_listings_by_external_ids(
    db: AsyncSession,
    *,
    tenant_id: int,
    external_ids: List[str],
) -> Dict[str, Listing]:
    """Fetch multiple listings by external_id in ONE query."""
    if not external_ids:
        return {}
    result = await db.execute(
        select(Listing).where(
            Listing.tenant_id == tenant_id,
            Listing.external_id.in_(external_ids),
            Listing.deleted_at.is_(None),
        )
    )
    return {lst.external_id: lst for lst in result.scalars().all()}


async def list_listings(
    db: AsyncSession,
    *,
    tenant_id: int,
    industry: Optional[str] = None,
    status_filter: Optional[str] = None,
    suburb: Optional[str] = None,
    attribute_filters: Optional[Dict] = None,
    limit: int = 50,
    offset: int = 0,
) -> Sequence[Listing]:
    q = select(Listing).where(
        Listing.tenant_id == tenant_id,
        Listing.deleted_at.is_(None),
    )
    if industry:
        q = q.where(Listing.industry == industry)
    if status_filter:
        q = q.where(Listing.status == status_filter)
    if suburb:
        q = q.where(Listing.suburb.ilike(f"%{suburb}%"))
    if attribute_filters:
        # JSONB containment filter — safe, no SQL injection (dict literal, not user string)
        q = q.where(Listing.attributes.contains(attribute_filters))
    q = q.order_by(Listing.updated_at.desc()).limit(limit).offset(offset)
    result = await db.execute(q)
    return result.scalars().all()


async def count_listings(
    db: AsyncSession,
    *,
    tenant_id: int,
    industry: Optional[str] = None,
    status_filter: Optional[str] = None,
    suburb: Optional[str] = None,
    attribute_filters: Optional[Dict] = None,
) -> int:
    q = select(func.count()).select_from(Listing).where(
        Listing.tenant_id == tenant_id,
        Listing.deleted_at.is_(None),
    )
    if industry:
        q = q.where(Listing.industry == industry)
    if status_filter:
        q = q.where(Listing.status == status_filter)
    if suburb:
        q = q.where(Listing.suburb.ilike(f"%{suburb}%"))
    if attribute_filters:
        q = q.where(Listing.attributes.contains(attribute_filters))
    result = await db.execute(q)
    return result.scalar_one()


async def create_listing(
    db: AsyncSession,
    *,
    tenant_id: int,
    public_id: str,
    source: str,
    title: str,
    industry: str = "real_estate",
    status: str = "active",
    crawl_job_id: Optional[int] = None,
    external_id: Optional[str] = None,
    description: Optional[str] = None,
    price: Optional[float] = None,
    price_display: Optional[str] = None,
    currency: str = "AUD",
    street: Optional[str] = None,
    suburb: Optional[str] = None,
    state: Optional[str] = None,
    postcode: Optional[str] = None,
    country: Optional[str] = None,
    attributes: Optional[dict] = None,
    media: Optional[list] = None,
    raw_data: Optional[dict] = None,
) -> Listing:
    listing = Listing(
        tenant_id=tenant_id,
        public_id=public_id,
        source=source,
        crawl_job_id=crawl_job_id,
        external_id=external_id,
        industry=industry,
        title=title,
        status=status,
        description=description,
        price=price,
        price_display=price_display,
        currency=currency,
        street=street,
        suburb=suburb,
        state=state,
        postcode=postcode,
        country=country,
        attributes=attributes or {},
        media=media or [],
        raw_data=raw_data or {},
    )
    db.add(listing)
    await db.flush()
    return listing


async def upsert_listing(
    db: AsyncSession,
    *,
    tenant_id: int,
    external_id: str,
    **fields,
) -> tuple[Listing, bool]:
    existing = await get_listing_by_external_id(
        db, tenant_id=tenant_id, external_id=external_id
    )
    if existing:
        for key, value in fields.items():
            if value is not None:
                setattr(existing, key, value)
        await db.flush()
        return existing, False

    listing = await create_listing(
        db, tenant_id=tenant_id, external_id=external_id, **fields
    )
    return listing, True


async def update_listing_embedding(
    db: AsyncSession,
    *,
    tenant_id: int,
    listing_id: int,
    embedding: list,
) -> None:
    await db.execute(
        update(Listing)
        .where(Listing.id == listing_id, Listing.tenant_id == tenant_id)
        .values(embedding=embedding)
    )


async def clear_listing_embedding(
    db: AsyncSession,
    *,
    tenant_id: int,
    listing_id: int,
) -> None:
    await db.execute(
        update(Listing)
        .where(Listing.id == listing_id, Listing.tenant_id == tenant_id)
        .values(embedding=None)
    )


async def get_listing_by_id(
    db: AsyncSession, *, tenant_id: int, listing_id: int
) -> Optional[Listing]:
    result = await db.execute(
        select(Listing).where(
            Listing.id == listing_id,
            Listing.tenant_id == tenant_id,
            Listing.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()
