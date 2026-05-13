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
    page_size: int,
    cursor: Optional[str] = None,
    industry: Optional[str] = None,
    suburb: Optional[str] = None,
    status_filter: Optional[str] = None,
    attribute_filters: Optional[dict] = None,
):
    """
    Cursor-paginated listings. Sort key: (updated_at, id) DESC — newest
    edits surface first. Returns a CursorPage[ListingResponse].
    """
    from app.core.pagination import CursorPage, decode_cursor

    cursor_dt = cursor_id = None
    if cursor:
        cursor_dt, cursor_id = decode_cursor(cursor)

    rows = await repo.list_listings_keyset(
        db,
        tenant_id=tenant_id,
        page_size=page_size,
        industry=industry,
        suburb=suburb,
        status_filter=status_filter,
        attribute_filters=attribute_filters,
        cursor_dt=cursor_dt,
        cursor_id=cursor_id,
    )
    page = CursorPage.build(rows, page_size, sort_attr="updated_at", id_attr="id")
    page.items = [schemas.ListingResponse.model_validate(lst) for lst in page.items]
    return page


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
    user_id: Optional[int] = None,
    request: Optional[Request] = None,
) -> schemas.ListingResponse:
    from app.modules.chatbot.tasks import embed_listing

    listing = await repo.create_listing(
        db,
        tenant_id=tenant_id,
        public_id=_new_public_id(),
        source=ListingSource.MANUAL.value,
        industry=payload.industry,
        title=payload.title,
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
        attributes=payload.attributes,
        media=payload.media,
    )
    await audit.write(
        db,
        entity_type="listings",
        action=audit.CREATE,
        tenant_id=tenant_id,
        user_id=user_id,
        entity_id=listing.id,
        diff={"after": {"title": listing.title, "industry": listing.industry}},
        request=request,
    )

    await db.commit()
    await db.refresh(listing)

    embed_listing.apply_async(kwargs=dict(listing_id=listing.id, tenant_id=tenant_id))
    logger.info("[listings] created public_id=%s title=%s industry=%s", listing.public_id, listing.title, listing.industry)
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Listing not found.")

    updates = payload.model_dump(exclude_none=True)

    # Merge attributes rather than replace — only provided keys are overwritten
    if "attributes" in updates and updates["attributes"] is not None:
        merged = dict(listing.attributes or {})
        merged.update(updates.pop("attributes"))
        listing.attributes = merged

    for key, value in updates.items():
        setattr(listing, key, value)

    await audit.write(
        db,
        entity_type="listings",
        action=audit.UPDATE,
        tenant_id=tenant_id,
        user_id=user_id,
        entity_id=listing.id,
        diff={"after": {k: str(v) for k, v in updates.items()}},
        request=request,
    )

    await db.commit()
    await db.refresh(listing)

    embed_listing.apply_async(kwargs=dict(listing_id=listing.id, tenant_id=tenant_id))
    logger.info("[listings] updated public_id=%s", listing.public_id)
    return schemas.ListingResponse.model_validate(listing)


async def delete_listing(
    db: AsyncSession, *, tenant_id: int, public_id: str,
    user_id: Optional[int] = None,
    request: Optional[Request] = None,
) -> None:
    from app.modules.chatbot.tasks import clear_listing_embedding

    listing = await repo.get_listing_by_public_id(db, tenant_id=tenant_id, public_id=public_id)
    if not listing:
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
    logger.info("[listings] soft-deleted public_id=%s", listing.public_id)


async def queue_listing_file_import(
    db: AsyncSession,
    *,
    tenant_id: int,
    file_bytes: bytes,
    filename: str,
    file_type: str,
    chatbot_config_id: Optional[int] = None,
    industry: str = "real_estate",
) -> schemas.ListingUploadJobResponse:
    """
    Store the uploaded file and dispatch a background Celery task.
    Returns immediately with a job record for status polling.
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
        chatbot_config_id=chatbot_config_id,
        industry=industry,
    )
    await db.commit()
    await db.refresh(job)

    process_listing_file.apply_async(
        kwargs=dict(job_id=job.id, tenant_id=tenant_id),
        queue=QUEUEEnum.ANALYSIS.value,
    )
    logger.info("[listings] upload job queued public_id=%s filename=%s industry=%s", job.public_id, filename, industry)
    return schemas.ListingUploadJobResponse.model_validate(job)


async def retry_listing_upload_job(
    db: AsyncSession,
    *,
    tenant_id: int,
    job_public_id: str,
) -> schemas.ListingUploadJobResponse:
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
    logger.info("[listings] upload job re-queued public_id=%s", job.public_id)
    return schemas.ListingUploadJobResponse.model_validate(job)
