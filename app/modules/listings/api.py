from __future__ import annotations

import asyncio
import logging
from typing import Annotated, List, Optional

import sentry_sdk
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.core.database import get_db
from app.core.response import ApiResponse, PagedApiResponse, PaginationMeta
from app.dependencies.tenant import TenantContext, get_tenant_context, require_write
from app.modules.listings import schemas, service

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter(prefix="/listings", tags=["Listings"])

DBDep = Annotated[AsyncSession, Depends(get_db)]
CtxDep = Annotated[TenantContext, Depends(get_tenant_context)]

_MAX_UPLOAD_BYTES = settings.MAX_UPLOAD_MB * 1024 * 1024

_EXCEL_MIME_TYPES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "application/octet-stream",
}

_CSV_MIME_TYPES = {
    "text/csv",
    "application/csv",
    "text/plain",
    "application/octet-stream",
}


# =============================================================================
# LISTINGS — collection + create
# =============================================================================

@router.get(
    "/{tenant_public_id}/listings",
    response_model=PagedApiResponse[List[schemas.ListingResponse]],
    summary="List all listings for the tenant",
)
async def list_listings(
    tenant_public_id: str,
    db: DBDep,
    ctx: CtxDep,
    suburb: Optional[str] = None,
    listing_type: Optional[str] = None,
    status_filter: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> PagedApiResponse[List[schemas.ListingResponse]]:
    try:
        data, total = await service.list_listings(
            db,
            tenant_id=ctx.tenant.id,
            suburb=suburb,
            listing_type=listing_type,
            status_filter=status_filter,
            limit=limit,
            offset=offset,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error listing listings tenant=%s", tenant_public_id)
        sentry_sdk.capture_exception()
        raise HTTPException(status_code=500, detail="Could not fetch listings. Please try again later.")
    return PagedApiResponse(
        success=True,
        message="OK",
        data=data,
        meta=PaginationMeta(
            total=total,
            limit=limit,
            offset=offset,
            has_next=offset + limit < total,
            has_prev=offset > 0,
        ),
    )


@router.post(
    "/{tenant_public_id}/listings",
    response_model=ApiResponse[schemas.ListingResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Create a listing manually",
)
async def create_listing(
    tenant_public_id: str,
    payload: schemas.ListingCreateRequest,
    request: Request,
    db: DBDep,
    ctx: CtxDep,
) -> ApiResponse[schemas.ListingResponse]:
    require_write(ctx)
    try:
        data = await service.create_listing(
            db,
            tenant_id=ctx.tenant.id,
            payload=payload,
            user_id=ctx.membership.user_id,
            request=request,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error creating listing tenant=%s", tenant_public_id)
        sentry_sdk.capture_exception()
        raise HTTPException(status_code=500, detail="Could not create listing. Please try again later.")
    return ApiResponse(success=True, message="Listing created.", data=data)


# =============================================================================
# UPLOAD JOBS — must be registered before /{listing_id} to avoid route conflict
# =============================================================================

@router.post(
    "/{tenant_public_id}/listings/upload",
    response_model=ApiResponse[schemas.ListingUploadJobResponse],
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload an Excel (.xlsx/.xls) or CSV (.csv) file — rows parsed by LLM and imported in background",
)
async def upload_listing_file(
    tenant_public_id: str,
    db: DBDep,
    ctx: CtxDep,
    file: UploadFile = File(..., description=".xlsx, .xls, or .csv file with one listing per row"),
) -> ApiResponse[schemas.ListingUploadJobResponse]:
    require_write(ctx)

    filename = file.filename or "listings.xlsx"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    content_type = file.content_type or "application/octet-stream"

    if ext in ("xlsx", "xls"):
        file_type = ext
    elif ext == "csv":
        file_type = "csv"
    elif content_type in _EXCEL_MIME_TYPES and content_type != "application/octet-stream":
        file_type = "xlsx"
    elif content_type in _CSV_MIME_TYPES and content_type != "application/octet-stream":
        file_type = "csv"
    else:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only Excel (.xlsx, .xls) or CSV (.csv) files are accepted for listing upload.",
        )

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(file_bytes) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the {settings.MAX_UPLOAD_MB} MB limit.",
        )

    try:
        data = await service.queue_listing_file_import(
            db,
            tenant_id=ctx.tenant.id,
            file_bytes=file_bytes,
            filename=filename,
            file_type=file_type,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception(
            "Unexpected error uploading listing file tenant=%s filename=%s",
            tenant_public_id, filename,
        )
        sentry_sdk.capture_exception()
        raise HTTPException(status_code=500, detail="Could not queue listing file. Please try again later.")
    return ApiResponse(
        success=True,
        message=f"'{filename}' queued for processing. Use public_id to poll status.",
        data=data,
    )


@router.get(
    "/{tenant_public_id}/listings/uploads",
    response_model=PagedApiResponse[List[schemas.ListingUploadJobResponse]],
    summary="List all listing file import jobs (all statuses)",
)
async def list_listing_upload_jobs(
    tenant_public_id: str,
    db: DBDep,
    ctx: CtxDep,
    status_filter: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> PagedApiResponse[List[schemas.ListingUploadJobResponse]]:
    from app.modules.chatbot import repository as chatbot_repo

    try:
        jobs, total = await asyncio.gather(
            chatbot_repo.list_listing_upload_jobs(
                db, tenant_id=ctx.tenant.id, status=status_filter, limit=limit, offset=offset
            ),
            chatbot_repo.count_listing_upload_jobs(
                db, tenant_id=ctx.tenant.id, status=status_filter
            ),
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error listing upload jobs tenant=%s", tenant_public_id)
        sentry_sdk.capture_exception()
        raise HTTPException(status_code=500, detail="Could not fetch upload jobs. Please try again later.")
    return PagedApiResponse(
        success=True,
        message="OK",
        data=[schemas.ListingUploadJobResponse.model_validate(j) for j in jobs],
        meta=PaginationMeta(
            total=total,
            limit=limit,
            offset=offset,
            has_next=offset + limit < total,
            has_prev=offset > 0,
        ),
    )


@router.get(
    "/{tenant_public_id}/listings/uploads/{job_id}",
    response_model=ApiResponse[schemas.ListingUploadJobResponse],
    summary="Poll the status of a listing file import job",
)
async def get_listing_upload_job(
    tenant_public_id: str,
    job_id: str,
    db: DBDep,
    ctx: CtxDep,
) -> ApiResponse[schemas.ListingUploadJobResponse]:
    from app.modules.chatbot import repository as chatbot_repo

    try:
        job = await chatbot_repo.get_listing_upload_job_by_public_id(
            db, tenant_id=ctx.tenant.id, public_id=job_id
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception(
            "Unexpected error fetching upload job tenant=%s job_id=%s",
            tenant_public_id, job_id,
        )
        sentry_sdk.capture_exception()
        raise HTTPException(status_code=500, detail="Could not fetch upload job. Please try again later.")
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload job not found.")
    return ApiResponse(
        success=True,
        message="OK",
        data=schemas.ListingUploadJobResponse.model_validate(job),
    )


@router.post(
    "/{tenant_public_id}/listings/uploads/{job_id}/retry",
    response_model=ApiResponse[schemas.ListingUploadJobResponse],
    status_code=status.HTTP_202_ACCEPTED,
    summary="Retry a failed listing file import job",
)
async def retry_listing_upload_job(
    tenant_public_id: str,
    job_id: str,
    db: DBDep,
    ctx: CtxDep,
) -> ApiResponse[schemas.ListingUploadJobResponse]:
    require_write(ctx)
    try:
        data = await service.retry_listing_upload_job(
            db, tenant_id=ctx.tenant.id, job_public_id=job_id
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception(
            "Unexpected error retrying upload job tenant=%s job_id=%s",
            tenant_public_id, job_id,
        )
        sentry_sdk.capture_exception()
        raise HTTPException(status_code=500, detail="Could not retry upload job. Please try again later.")
    return ApiResponse(
        success=True,
        message="Job re-queued for processing.",
        data=data,
    )


# =============================================================================
# LISTINGS — single item (dynamic segment — must come AFTER all static routes)
# =============================================================================

@router.get(
    "/{tenant_public_id}/listings/{listing_id}",
    response_model=ApiResponse[schemas.ListingResponse],
    summary="Get a single listing",
)
async def get_listing(
    tenant_public_id: str,
    listing_id: str,
    db: DBDep,
    ctx: CtxDep,
) -> ApiResponse[schemas.ListingResponse]:
    try:
        data = await service.get_listing(db, tenant_id=ctx.tenant.id, public_id=listing_id)
    except HTTPException:
        raise
    except Exception:
        logger.exception(
            "Unexpected error fetching listing tenant=%s listing_id=%s",
            tenant_public_id, listing_id,
        )
        sentry_sdk.capture_exception()
        raise HTTPException(status_code=500, detail="Could not fetch listing. Please try again later.")
    return ApiResponse(success=True, message="OK", data=data)


@router.patch(
    "/{tenant_public_id}/listings/{listing_id}",
    response_model=ApiResponse[schemas.ListingResponse],
    summary="Update a listing",
)
async def update_listing(
    tenant_public_id: str,
    listing_id: str,
    payload: schemas.ListingUpdateRequest,
    request: Request,
    db: DBDep,
    ctx: CtxDep,
) -> ApiResponse[schemas.ListingResponse]:
    require_write(ctx)
    try:
        data = await service.update_listing(
            db,
            tenant_id=ctx.tenant.id,
            public_id=listing_id,
            payload=payload,
            user_id=ctx.membership.user_id,
            request=request,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception(
            "Unexpected error updating listing tenant=%s listing_id=%s",
            tenant_public_id, listing_id,
        )
        sentry_sdk.capture_exception()
        raise HTTPException(status_code=500, detail="Could not update listing. Please try again later.")
    return ApiResponse(success=True, message="Listing updated.", data=data)


@router.delete(
    "/{tenant_public_id}/listings/{listing_id}",
    status_code=status.HTTP_200_OK,
    response_model=ApiResponse[dict],
    summary="Soft-delete a listing",
)
async def delete_listing(
    tenant_public_id: str,
    listing_id: str,
    request: Request,
    db: DBDep,
    ctx: CtxDep,
) -> ApiResponse[dict]:
    require_write(ctx)
    try:
        await service.delete_listing(
            db,
            tenant_id=ctx.tenant.id,
            public_id=listing_id,
            user_id=ctx.membership.user_id,
            request=request,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception(
            "Unexpected error deleting listing tenant=%s listing_id=%s",
            tenant_public_id, listing_id,
        )
        sentry_sdk.capture_exception()
        raise HTTPException(status_code=500, detail="Could not delete listing. Please try again later.")
    return ApiResponse(success=True, message="Listing deleted.", data={})
