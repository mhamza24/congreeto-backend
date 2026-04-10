from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_base import _new_public_id
from app.core.enums import ListingSource, UploadJobStatus
from app.modules.listings import repository as repo
from app.modules.listings import schemas


async def list_listings(
    db: AsyncSession,
    *,
    tenant_id: int,
    suburb: Optional[str] = None,
    listing_type: Optional[str] = None,
    status_filter: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Tuple[List[schemas.ListingResponse], int]:
    listings, total = await asyncio.gather(
        repo.list_listings(
            db,
            tenant_id=tenant_id,
            suburb=suburb,
            listing_type=listing_type,
            status_filter=status_filter,
            limit=limit,
            offset=offset,
        ),
        repo.count_listings(
            db,
            tenant_id=tenant_id,
            suburb=suburb,
            listing_type=listing_type,
            status_filter=status_filter,
        ),
    )
    return [schemas.ListingResponse.model_validate(lst) for lst in listings], total


async def get_listing(
    db: AsyncSession, *, tenant_id: int, public_id: str
) -> schemas.ListingResponse:
    listing = await repo.get_listing_by_public_id(db, tenant_id=tenant_id, public_id=public_id)
    if not listing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Listing not found.")
    return schemas.ListingResponse.model_validate(listing)


async def create_listing(
    db: AsyncSession,
    *,
    tenant_id: int,
    payload: schemas.ListingCreateRequest,
) -> schemas.ListingResponse:
    from app.modules.chatbot.tasks import embed_listing

    listing = await repo.create_listing(
        db,
        tenant_id=tenant_id,
        public_id=_new_public_id(),
        source=ListingSource.MANUAL.value,
        title=payload.title,
        listing_type=payload.listing_type,
        status=payload.status,
        description=payload.description,
        price=payload.price,
        price_display=payload.price_display,
        currency=payload.currency,
        street=payload.street,
        suburb=payload.suburb,
        state=payload.state,
        postcode=payload.postcode,
        country=payload.country,
        bedrooms=payload.bedrooms,
        bathrooms=payload.bathrooms,
        garages=payload.garages,
        land_sqm=payload.land_sqm,
        house_sqm=payload.house_sqm,
        has_pool=payload.has_pool,
        media=payload.media,
    )
    await db.commit()
    await db.refresh(listing)

    embed_listing.apply_async(kwargs=dict(listing_id=listing.id, tenant_id=tenant_id))
    return schemas.ListingResponse.model_validate(listing)


async def update_listing(
    db: AsyncSession,
    *,
    tenant_id: int,
    public_id: str,
    payload: schemas.ListingUpdateRequest,
) -> schemas.ListingResponse:
    from app.modules.chatbot.tasks import embed_listing

    listing = await repo.get_listing_by_public_id(db, tenant_id=tenant_id, public_id=public_id)
    if not listing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Listing not found.")

    for key, value in payload.model_dump(exclude_none=True).items():
        setattr(listing, key, value)
    await db.commit()
    await db.refresh(listing)

    embed_listing.apply_async(kwargs=dict(listing_id=listing.id, tenant_id=tenant_id))
    return schemas.ListingResponse.model_validate(listing)


async def delete_listing(
    db: AsyncSession, *, tenant_id: int, public_id: str
) -> None:
    from app.modules.chatbot.tasks import clear_listing_embedding

    listing = await repo.get_listing_by_public_id(db, tenant_id=tenant_id, public_id=public_id)
    if not listing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Listing not found.")

    listing.deleted_at = datetime.now(timezone.utc)
    await db.commit()

    clear_listing_embedding.apply_async(kwargs=dict(listing_id=listing.id, tenant_id=tenant_id))


async def queue_listing_file_import(
    db: AsyncSession,
    *,
    tenant_id: int,
    file_bytes: bytes,
    filename: str,
    file_type: str,
) -> schemas.ListingUploadJobResponse:
    """
    Store the uploaded file as a blob and dispatch a background Celery task
    to parse (via LLM), upsert, and embed all listing rows.
    Returns immediately with a job record so the caller can poll status.
    """
    from app.modules.chatbot import repository as chatbot_repo
    from app.modules.chatbot.tasks import process_listing_file
    from app.config.celery_worker import QUEUEEnum

    job = await chatbot_repo.create_listing_upload_job(
        db,
        tenant_id=tenant_id,
        public_id=_new_public_id(),
        filename=filename,
        file_type=file_type,
        file_data=file_bytes,
    )
    await db.commit()
    await db.refresh(job)

    process_listing_file.apply_async(
        kwargs=dict(job_id=job.id, tenant_id=tenant_id),
        queue=QUEUEEnum.ANALYSIS.value,
    )

    return schemas.ListingUploadJobResponse.model_validate(job)


async def retry_listing_upload_job(
    db: AsyncSession,
    *,
    tenant_id: int,
    job_public_id: str,
) -> schemas.ListingUploadJobResponse:
    """Re-queue a failed (or stuck) listing upload job."""
    from app.modules.chatbot import repository as chatbot_repo
    from app.modules.chatbot.tasks import process_listing_file
    from app.config.celery_worker import QUEUEEnum

    job = await chatbot_repo.get_listing_upload_job_by_public_id(
        db, tenant_id=tenant_id, public_id=job_public_id
    )
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload job not found.")

    if job.status not in (UploadJobStatus.FAILED, UploadJobStatus.QUEUED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Job is currently '{job.status}'. Only failed or queued jobs can be retried.",
        )

    await chatbot_repo.update_listing_upload_job(
        db, job=job, status=UploadJobStatus.QUEUED, processed_rows=0, error_message=None
    )
    await db.commit()
    await db.refresh(job)

    process_listing_file.apply_async(
        kwargs=dict(job_id=job.id, tenant_id=tenant_id),
        queue=QUEUEEnum.ANALYSIS.value,
    )

    return schemas.ListingUploadJobResponse.model_validate(job)


async def import_from_excel(
    db: AsyncSession,
    *,
    tenant_id: int,
    file_bytes: bytes,
    filename: str,
) -> schemas.ListingImportResponse:
    from app.modules.chatbot.parsers.excel_parser import parse_excel_listings
    from app.modules.chatbot.tasks import embed_listing

    try:
        rows = parse_excel_listings(file_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if not rows:
        raise HTTPException(status_code=422, detail="No valid listing rows found in the file.")

    imported = 0
    for item in rows:
        external_id = f"excel::{filename}::{item.get('title', '')}::{item.get('suburb', '')}"
        existing = await repo.get_listing_by_external_id(
            db, tenant_id=tenant_id, external_id=external_id
        )
        listing, _ = await repo.upsert_listing(
            db,
            tenant_id=tenant_id,
            external_id=external_id,
            public_id=_new_public_id() if not existing else existing.public_id,
            source=ListingSource.MANUAL.value,
            title=item.get("title", "Untitled"),
            listing_type=item.get("listing_type", "sale"),
            status=item.get("status", "active"),
            description=item.get("description"),
            price=item.get("price"),
            price_display=item.get("price_display"),
            currency=item.get("currency", "AUD"),
            street=item.get("street"),
            suburb=item.get("suburb"),
            state=item.get("state"),
            postcode=item.get("postcode"),
            bedrooms=item.get("bedrooms"),
            bathrooms=item.get("bathrooms"),
            garages=item.get("garages"),
            land_sqm=item.get("land_sqm"),
            house_sqm=item.get("house_sqm"),
            has_pool=item.get("has_pool", False),
            raw_data=item.get("raw_data", {}),
        )
        await db.commit()
        embed_listing.apply_async(kwargs=dict(listing_id=listing.id, tenant_id=tenant_id))
        imported += 1

    return schemas.ListingImportResponse(imported=imported, filename=filename)
