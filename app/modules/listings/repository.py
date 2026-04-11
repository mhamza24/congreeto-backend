from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from sqlalchemy import func, select, update
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
    """Fetch multiple listings by external_id in ONE query.
    Returns a dict keyed by external_id for O(1) lookup."""
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
    suburb: Optional[str] = None,
    listing_type: Optional[str] = None,
    status_filter: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Sequence[Listing]:
    q = select(Listing).where(
        Listing.tenant_id == tenant_id,
        Listing.deleted_at.is_(None),
    )
    if suburb:
        q = q.where(Listing.suburb.ilike(f"%{suburb}%"))
    if listing_type:
        q = q.where(Listing.listing_type == listing_type)
    if status_filter:
        q = q.where(Listing.status == status_filter)
    q = q.order_by(Listing.updated_at.desc()).limit(limit).offset(offset)
    result = await db.execute(q)
    return result.scalars().all()


async def count_listings(
    db: AsyncSession,
    *,
    tenant_id: int,
    suburb: Optional[str] = None,
    listing_type: Optional[str] = None,
    status_filter: Optional[str] = None,
) -> int:
    q = select(func.count()).select_from(Listing).where(
        Listing.tenant_id == tenant_id,
        Listing.deleted_at.is_(None),
    )
    if suburb:
        q = q.where(Listing.suburb.ilike(f"%{suburb}%"))
    if listing_type:
        q = q.where(Listing.listing_type == listing_type)
    if status_filter:
        q = q.where(Listing.status == status_filter)
    result = await db.execute(q)
    return result.scalar_one()


async def create_listing(
    db: AsyncSession,
    *,
    tenant_id: int,
    public_id: str,
    source: str,
    title: str,
    listing_type: str,
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
    country: str = "AU",
    bedrooms: Optional[int] = None,
    bathrooms: Optional[int] = None,
    garages: Optional[int] = None,
    land_sqm: Optional[float] = None,
    house_sqm: Optional[float] = None,
    has_pool: bool = False,
    media: Optional[list] = None,
    raw_data: Optional[dict] = None,
) -> Listing:
    listing = Listing(
        tenant_id=tenant_id,
        public_id=public_id,
        source=source,
        crawl_job_id=crawl_job_id,
        external_id=external_id,
        title=title,
        listing_type=listing_type,
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
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        garages=garages,
        land_sqm=land_sqm,
        house_sqm=house_sqm,
        has_pool=has_pool,
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
