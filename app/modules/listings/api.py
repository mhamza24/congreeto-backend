from __future__ import annotations

from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.core.database import get_db
from app.core.response import ApiResponse
from app.dependencies.tenant import TenantContext, get_tenant_context, require_write
from app.modules.listings import schemas, service

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


@router.get(
    "/{tenant_public_id}/listings",
    response_model=ApiResponse[List[schemas.ListingResponse]],
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
) -> ApiResponse[List[schemas.ListingResponse]]:
    data = await service.list_listings(
        db,
        tenant_id=ctx.tenant.id,
        suburb=suburb,
        listing_type=listing_type,
        status_filter=status_filter,
        limit=limit,
        offset=offset,
    )
    return ApiResponse(success=True, message="OK", data=data)


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
    data = await service.get_listing(db, tenant_id=ctx.tenant.id, public_id=listing_id)
    return ApiResponse(success=True, message="OK", data=data)


@router.post(
    "/{tenant_public_id}/listings",
    response_model=ApiResponse[schemas.ListingResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Create a listing manually",
)
async def create_listing(
    tenant_public_id: str,
    payload: schemas.ListingCreateRequest,
    db: DBDep,
    ctx: CtxDep,
) -> ApiResponse[schemas.ListingResponse]:
    require_write(ctx)
    data = await service.create_listing(db, tenant_id=ctx.tenant.id, payload=payload)
    return ApiResponse(success=True, message="Listing created.", data=data)


@router.patch(
    "/{tenant_public_id}/listings/{listing_id}",
    response_model=ApiResponse[schemas.ListingResponse],
    summary="Update a listing",
)
async def update_listing(
    tenant_public_id: str,
    listing_id: str,
    payload: schemas.ListingUpdateRequest,
    db: DBDep,
    ctx: CtxDep,
) -> ApiResponse[schemas.ListingResponse]:
    require_write(ctx)
    data = await service.update_listing(
        db, tenant_id=ctx.tenant.id, public_id=listing_id, payload=payload
    )
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
    db: DBDep,
    ctx: CtxDep,
) -> ApiResponse[dict]:
    require_write(ctx)
    await service.delete_listing(db, tenant_id=ctx.tenant.id, public_id=listing_id)
    return ApiResponse(success=True, message="Listing deleted.", data={})


@router.post(
    "/{tenant_public_id}/listings/upload",
    response_model=ApiResponse[schemas.ListingImportResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Upload an Excel (.xlsx) file — each row becomes a Listing record",
)
async def upload_listing_excel(
    tenant_public_id: str,
    db: DBDep,
    ctx: CtxDep,
    file: UploadFile = File(..., description=".xlsx file with one listing per row"),
) -> ApiResponse[schemas.ListingImportResponse]:
    require_write(ctx)

    filename = file.filename or "listings.xlsx"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    content_type = file.content_type or "application/octet-stream"

    if content_type not in _EXCEL_MIME_TYPES and ext not in ("xlsx", "xls"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only Excel files (.xlsx) are accepted for listing upload.",
        )

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(file_bytes) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the {settings.MAX_UPLOAD_MB} MB limit.",
        )

    data = await service.import_from_excel(
        db, tenant_id=ctx.tenant.id, file_bytes=file_bytes, filename=filename
    )
    return ApiResponse(
        success=True,
        message=f"{data.imported} listing(s) imported from '{filename}'.",
        data=data,
    )
