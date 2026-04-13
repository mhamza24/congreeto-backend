from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_base import _new_public_id
from app.core.enums import ListingSource, UploadJobStatus
from app.modules.audit import repository as audit
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
    logger.debug("[listings] list_listings total=%d limit=%d offset=%d", total, limit, offset)
    return [schemas.ListingResponse.model_validate(lst) for lst in listings], total


async def get_listing(
    db: AsyncSession, *, tenant_id: int, public_id: str
) -> schemas.ListingResponse:
    listing = await repo.get_listing_by_public_id(db, tenant_id=tenant_id, public_id=public_id)
    if not listing:
        logger.warning("[listings] get_listing not found public_id=%s", public_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Listing not found.")
    logger.debug("[listings] get_listing found public_id=%s", public_id)
    return schemas.ListingResponse.model_validate(listing)


async def create_listing(
    db: AsyncSession,
    *,
    tenant_id: int,
    payload: schemas.ListingCreateRequest,
    user_id: Optional[int] = None,
    request: Optional[Request] = None,
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
    await audit.write(
        db,
        entity_type="listings",
        action=audit.CREATE,
        tenant_id=tenant_id,
        user_id=user_id,
        entity_id=listing.id,
        diff={"after": {"title": listing.title, "listing_type": str(listing.listing_type)}},
        request=request,
    )

    await db.commit()
    await db.refresh(listing)

    embed_listing.apply_async(kwargs=dict(listing_id=listing.id, tenant_id=tenant_id))
    logger.info("[listings] listing created public_id=%s title=%s", listing.public_id, listing.title)
    return schemas.ListingResponse.model_validate(listing)


async def update_listing(
    db: AsyncSession,
    *,
    tenant_id: int,
    public_id: str,
    payload: schemas.ListingUpdateRequest,
    user_id: Optional[int] = None,
    request: Optional[Request] = None,
) -> schemas.ListingResponse:
    from app.modules.chatbot.tasks import embed_listing

    listing = await repo.get_listing_by_public_id(db, tenant_id=tenant_id, public_id=public_id)
    if not listing:
        logger.warning("[listings] update_listing not found public_id=%s", public_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Listing not found.")

    changed_fields = list(payload.model_dump(exclude_none=True).keys())
    for key, value in payload.model_dump(exclude_none=True).items():
        setattr(listing, key, value)

    await audit.write(
        db,
        entity_type="listings",
        action=audit.UPDATE,
        tenant_id=tenant_id,
        user_id=user_id,
        entity_id=listing.id,
        diff={"after": {k: str(v) for k, v in payload.model_dump(exclude_none=True).items()}},
        request=request,
    )

    await db.commit()
    await db.refresh(listing)

    embed_listing.apply_async(kwargs=dict(listing_id=listing.id, tenant_id=tenant_id))
    logger.info("[listings] listing updated public_id=%s fields=%s", listing.public_id, changed_fields)
    return schemas.ListingResponse.model_validate(listing)


async def delete_listing(
    db: AsyncSession, *, tenant_id: int, public_id: str,
    user_id: Optional[int] = None,
    request: Optional[Request] = None,
) -> None:
    from app.modules.chatbot.tasks import clear_listing_embedding

    listing = await repo.get_listing_by_public_id(db, tenant_id=tenant_id, public_id=public_id)
    if not listing:
        logger.warning("[listings] delete_listing not found public_id=%s", public_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Listing not found.")

    listing.deleted_at = datetime.now(timezone.utc)

    await audit.write(
        db,
        entity_type="listings",
        action=audit.DELETE,
        tenant_id=tenant_id,
        user_id=user_id,
        entity_id=listing.id,
        diff={"before": {"title": listing.title}},
        request=request,
    )

    await db.commit()

    clear_listing_embedding.apply_async(kwargs=dict(listing_id=listing.id, tenant_id=tenant_id))
    logger.info("[listings] listing soft-deleted public_id=%s", listing.public_id)


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
    logger.info("[listings] upload job queued public_id=%s filename=%s file_type=%s", job.public_id, filename, file_type)

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
        logger.warning("[listings] retry_job not found public_id=%s", job_public_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload job not found.")

    if job.status not in (UploadJobStatus.FAILED, UploadJobStatus.QUEUED):
        logger.warning("[listings] retry_job invalid status public_id=%s status=%s", job.public_id, job.status)
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
    logger.info("[listings] upload job re-queued public_id=%s", job.public_id)

    return schemas.ListingUploadJobResponse.model_validate(job)


async def import_from_excel(
    db: AsyncSession,
    *,
    tenant_id: int,
    file_bytes: bytes,
    filename: str,
) -> schemas.ListingImportResponse:
    from app.modules.chatbot.parsers.excel_parser import parse_excel_listings

    try:
        rows = parse_excel_listings(file_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if not rows:
        raise HTTPException(status_code=422, detail="No valid listing rows found in the file.")

    from app.modules.chatbot.tasks import embed_listings_batch, _EMBED_BATCH_SIZE

    _IMPORT_BATCH = 100
    imported = 0

    for batch_start in range(0, len(rows), _IMPORT_BATCH):
        batch = rows[batch_start: batch_start + _IMPORT_BATCH]

        # Build external_ids for the whole batch
        external_ids = [
            f"excel::{filename}::{item.get('title', '')}::{item.get('suburb', '')}"
            for item in batch
        ]

        # ONE query for all existing listings in this batch
        existing_map = await repo.get_listings_by_external_ids(
            db, tenant_id=tenant_id, external_ids=external_ids
        )

        batch_listing_ids: List[int] = []
        for item, external_id in zip(batch, external_ids):
            existing = existing_map.get(external_id)
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
            batch_listing_ids.append(listing.id)
            imported += 1

        # ONE commit for the whole batch
        await db.commit()

        # ONE embed task per _EMBED_BATCH_SIZE chunk (avoids oversized payloads)
        for i in range(0, len(batch_listing_ids), _EMBED_BATCH_SIZE):
            embed_listings_batch.apply_async(
                kwargs=dict(
                    listing_ids=batch_listing_ids[i: i + _EMBED_BATCH_SIZE],
                    tenant_id=tenant_id,
                )
            )

    return schemas.ListingImportResponse(imported=imported, filename=filename)
