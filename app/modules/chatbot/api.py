"""
app/modules/knowledge/api.py

All routes are tenant-scoped via {tenant_public_id} in the URL.
TenantContext dependency handles all gate checks (status, membership, billing).

  POST   /knowledge/{tenant_public_id}/chatbots
  GET    /knowledge/{tenant_public_id}/chatbots
  GET    /knowledge/{tenant_public_id}/chatbots/{chatbot_id}
  PATCH  /knowledge/{tenant_public_id}/chatbots/{chatbot_id}
  POST   /knowledge/{tenant_public_id}/chatbots/{chatbot_id}/activate

  GET    /knowledge/{tenant_public_id}/chatbots/{chatbot_id}/themes
  POST   /knowledge/{tenant_public_id}/chatbots/{chatbot_id}/themes
  PATCH  /knowledge/{tenant_public_id}/chatbots/{chatbot_id}/themes/{theme_id}
  POST   /knowledge/{tenant_public_id}/chatbots/{chatbot_id}/themes/{theme_id}/activate

  POST   /knowledge/{tenant_public_id}/chatbots/{chatbot_id}/assets
  GET    /knowledge/assets/{asset_public_id}          ← public, no auth (widget rendering)

  POST   /knowledge/{tenant_public_id}/chatbots/{chatbot_id}/knowledge-sources
  GET    /knowledge/{tenant_public_id}/chatbots/{chatbot_id}/knowledge-sources

  POST   /knowledge/{tenant_public_id}/chatbots/{chatbot_id}/knowledge-sources/{ks_id}/crawl-jobs
  GET    /knowledge/{tenant_public_id}/chatbots/{chatbot_id}/knowledge-sources/{ks_id}/crawl-jobs

  POST   /knowledge/{tenant_public_id}/chatbots/{chatbot_id}/knowledge-sources/{ks_id}/documents
  GET    /knowledge/{tenant_public_id}/chatbots/{chatbot_id}/knowledge-sources/{ks_id}/documents

  POST   /knowledge/{tenant_public_id}/chatbots/{chatbot_id}/knowledge-sources/{ks_id}/manual-entries

  POST   /knowledge/embeddings/links_scrap   ← legacy
  POST   /knowledge/embeddings/pdf           ← legacy
"""

from __future__ import annotations

import logging
from typing import Annotated, List, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.core.database import get_db
from app.core.response import ApiResponse
from app.dependencies.auth import require_superadmin
from app.dependencies.tenant import TenantContext, get_tenant_context, require_write
from app.modules.chatbot import schemas, service
from app.modules.chatbot import repository as repo
from app.config.celery_worker import QUEUEEnum
from app.modules.chatbot.tasks import crawl_and_embed
from app.core.enums import CrawlStatus
from app.modules.chatbot.parsers.pdf_parser import (
    _empty_result,
    _filename_from_path,
    _parse_pdf,
    read_pdf,
)

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/chatbot", tags=["Chatbot"])

DBDep = Annotated[AsyncSession, Depends(get_db)]
CtxDep = Annotated[TenantContext, Depends(get_tenant_context)]

# Hard per-file cap regardless of plan
_MAX_UPLOAD_BYTES = settings.MAX_UPLOAD_MB * 1024 * 1024


# =============================================================================
# ADMIN — cross-tenant chatbot management (super admin only)
# =============================================================================


@router.get(
    "/admin/chatbots",
    response_model=ApiResponse[List[schemas.ChatbotResponse]],
    summary="List all chatbots across all tenants (admin only)",
)
async def admin_list_chatbots(
    db: DBDep,
    current_user=Depends(require_superadmin),
) -> ApiResponse[List[schemas.ChatbotResponse]]:
    data = await service.admin_list_chatbots(db)
    return ApiResponse(success=True, message="OK", data=data)


@router.patch(
    "/admin/chatbots/{chatbot_id}/status",
    response_model=ApiResponse[schemas.ChatbotResponse],
    summary="Force-set chatbot status for any tenant (admin only)",
)
async def admin_set_chatbot_status(
    chatbot_id: str,
    payload: schemas.AdminChatbotStatusRequest,
    db: DBDep,
    current_user=Depends(require_superadmin),
) -> ApiResponse[schemas.ChatbotResponse]:
    data = await service.admin_set_chatbot_status(
        db, chatbot_public_id=chatbot_id, new_status=payload.status
    )
    return ApiResponse(success=True, message=f"Chatbot status set to '{payload.status}'.", data=data)


@router.delete(
    "/admin/chatbots/{chatbot_id}",
    response_model=ApiResponse[None],
    summary="Force-delete a chatbot for any tenant (admin only)",
)
async def admin_delete_chatbot(
    chatbot_id: str,
    db: DBDep,
    current_user=Depends(require_superadmin),
) -> ApiResponse[None]:
    await service.admin_delete_chatbot(db, chatbot_public_id=chatbot_id)
    return ApiResponse(success=True, message="Chatbot deleted.", data=None)


# =============================================================================
# CHATBOT CONFIG
# =============================================================================


@router.post(
    "/{tenant_public_id}/chatbots",
    response_model=ApiResponse[schemas.ChatbotResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Create a new chatbot (also creates a default widget theme)",
)
async def create_chatbot(
    payload: schemas.ChatbotCreateRequest,
    db: DBDep,
    ctx: CtxDep,
) -> ApiResponse[schemas.ChatbotResponse]:
    require_write(ctx)
    data = await service.create_chatbot(
        db,
        tenant_id=ctx.tenant.id,
        payload=payload,
    )
    return ApiResponse(success=True, message="Chatbot created.", data=data)


@router.get(
    "/{tenant_public_id}/chatbots",
    response_model=ApiResponse[List[schemas.ChatbotResponse]],
    summary="List all chatbots for the tenant",
)
async def list_chatbots(
    db: DBDep,
    ctx: CtxDep,
) -> ApiResponse[List[schemas.ChatbotResponse]]:
    data = await service.list_chatbots(db, tenant_id=ctx.tenant.id)
    return ApiResponse(success=True, message="chatbot(s) retrieved", data=data)


@router.get(
    "/{tenant_public_id}/chatbots/{chatbot_id}",
    response_model=ApiResponse[schemas.ChatbotResponse],
    summary="Get a single chatbot",
)
async def get_chatbot(
    chatbot_id: str,
    db: DBDep,
    ctx: CtxDep,
) -> ApiResponse[schemas.ChatbotResponse]:
    data = await service.get_chatbot(db, tenant_id=ctx.tenant.id, public_id=chatbot_id)
    return ApiResponse(success=True, message="OK", data=data)


@router.patch(
    "/{tenant_public_id}/chatbots/{chatbot_id}",
    response_model=ApiResponse[schemas.ChatbotResponse],
    summary="Update chatbot settings",
)
async def update_chatbot(
    chatbot_id: str,
    payload: schemas.ChatbotUpdateRequest,
    db: DBDep,
    ctx: CtxDep,
) -> ApiResponse[schemas.ChatbotResponse]:
    require_write(ctx)
    data = await service.update_chatbot(
        db,
        tenant_id=ctx.tenant.id,
        public_id=chatbot_id,
        payload=payload,
    )
    return ApiResponse(success=True, message="Chatbot updated.", data=data)


@router.post(
    "/{tenant_public_id}/chatbots/{chatbot_id}/activate",
    response_model=ApiResponse[schemas.ChatbotResponse],
    summary="Activate chatbot — validates that knowledge sources are ready",
)
async def activate_chatbot(
    chatbot_id: str,
    db: DBDep,
    ctx: CtxDep,
) -> ApiResponse[schemas.ChatbotResponse]:
    require_write(ctx)
    data = await service.activate_chatbot(
        db, tenant_id=ctx.tenant.id, public_id=chatbot_id
    )
    return ApiResponse(success=True, message="Chatbot is now active.", data=data)


# =============================================================================
# WIDGET THEMES
# =============================================================================


@router.get(
    "/{tenant_public_id}/chatbots/{chatbot_id}/themes",
    response_model=ApiResponse[List[schemas.ThemeResponse]],
    summary="List all themes for a chatbot",
)
async def list_themes(
    chatbot_id: str,
    db: DBDep,
    ctx: CtxDep,
) -> ApiResponse[List[schemas.ThemeResponse]]:
    data = await service.list_themes(
        db, tenant_id=ctx.tenant.id, chatbot_public_id=chatbot_id
    )
    return ApiResponse(success=True, message="OK", data=data)


@router.post(
    "/{tenant_public_id}/chatbots/{chatbot_id}/themes",
    response_model=ApiResponse[schemas.ThemeResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Create a new theme (inactive by default — call /activate to go live)",
)
async def create_theme(
    chatbot_id: str,
    payload: schemas.ThemeCreateRequest,
    db: DBDep,
    ctx: CtxDep,
) -> ApiResponse[schemas.ThemeResponse]:
    require_write(ctx)
    data = await service.create_theme(
        db,
        tenant_id=ctx.tenant.id,
        chatbot_public_id=chatbot_id,
        payload=payload,
    )
    return ApiResponse(success=True, message="Theme created.", data=data)


@router.patch(
    "/{tenant_public_id}/chatbots/{chatbot_id}/themes/{theme_id}",
    response_model=ApiResponse[schemas.ThemeResponse],
    summary="Update theme colors, typography, assets, or layout",
)
async def update_theme(
    chatbot_id: str,
    theme_id: str,
    payload: schemas.ThemeUpdateRequest,
    db: DBDep,
    ctx: CtxDep,
) -> ApiResponse[schemas.ThemeResponse]:
    require_write(ctx)
    data = await service.update_theme(
        db,
        tenant_id=ctx.tenant.id,
        chatbot_public_id=chatbot_id,
        theme_public_id=theme_id,
        payload=payload,
    )
    return ApiResponse(success=True, message="Theme updated.", data=data)


@router.post(
    "/{tenant_public_id}/chatbots/{chatbot_id}/themes/{theme_id}/activate",
    response_model=ApiResponse[schemas.ThemeResponse],
    summary="Activate a theme — deactivates all others atomically",
)
async def activate_theme(
    chatbot_id: str,
    theme_id: str,
    db: DBDep,
    ctx: CtxDep,
) -> ApiResponse[schemas.ThemeResponse]:
    require_write(ctx)
    data = await service.activate_theme(
        db,
        tenant_id=ctx.tenant.id,
        chatbot_public_id=chatbot_id,
        theme_public_id=theme_id,
    )
    return ApiResponse(success=True, message="Theme activated.", data=data)


# =============================================================================
# CHATBOT ASSETS  (logo, avatar, banner — stored as blob)
# =============================================================================


@router.post(
    "/{tenant_public_id}/chatbots/{chatbot_id}/assets",
    response_model=ApiResponse[schemas.AssetUploadResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Upload a chatbot image asset (logo, avatar, banner, gif)",
)
async def upload_asset(
    chatbot_id: str,
    db: DBDep,
    ctx: CtxDep,
    request: Request,
    asset_type: str = Form(
        ...,
        description="One of: logo | avatar | banner | gif | ribbon_icon",
    ),
    file: UploadFile = File(..., description="Image file (PNG, JPEG, GIF, WebP, SVG)"),
) -> ApiResponse[schemas.AssetUploadResponse]:
    require_write(ctx)

    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )

    base_url = str(request.base_url).rstrip("/")
    data = await service.upload_chatbot_asset(
        db,
        tenant_id=ctx.tenant.id,
        chatbot_public_id=chatbot_id,
        asset_type=asset_type,
        file_name=file.filename or f"{asset_type}.bin",
        content_type=file.content_type or "application/octet-stream",
        file_size_bytes=len(image_bytes),
        file_data=image_bytes,
        base_url=base_url,
    )
    return ApiResponse(success=True, message="Asset uploaded.", data=data)


@router.get(
    "/assets/{asset_public_id}",
    summary="Serve a chatbot asset (publicly accessible — used by the widget)",
    response_class=Response,
)
async def serve_asset(
    asset_public_id: str,
    db: DBDep,
) -> Response:
    """
    No auth required — the public_id is the access token.
    Widget iframe can load logo/avatar/banner directly via this URL.
    """
    asset = await repo.get_asset_by_public_id(db, public_id=asset_public_id)
    if not asset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found."
        )

    return Response(
        content=bytes(asset.file_data),
        media_type=asset.content_type,
        headers={
            "Cache-Control": "public, max-age=86400",  # 24h browser cache
            "Content-Disposition": f'inline; filename="{asset.file_name}"',
        },
    )


# =============================================================================
# KNOWLEDGE SOURCES
# =============================================================================


@router.post(
    "/{tenant_public_id}/chatbots/{chatbot_id}/knowledge-sources",
    response_model=ApiResponse[schemas.KnowledgeSourceResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Create a knowledge source (website | document | manual_qa)",
)
async def create_knowledge_source(
    chatbot_id: str,
    payload: schemas.KnowledgeSourceCreateRequest,
    db: DBDep,
    ctx: CtxDep,
) -> ApiResponse[schemas.KnowledgeSourceResponse]:
    require_write(ctx)
    data = await service.create_knowledge_source(
        db,
        tenant_id=ctx.tenant.id,
        chatbot_public_id=chatbot_id,
        payload=payload,
    )
    return ApiResponse(success=True, message="Knowledge source created.", data=data)


@router.get(
    "/{tenant_public_id}/chatbots/{chatbot_id}/knowledge-sources",
    response_model=ApiResponse[List[schemas.KnowledgeSourceResponse]],
    summary="List knowledge sources for a chatbot",
)
async def list_knowledge_sources(
    chatbot_id: str,
    db: DBDep,
    ctx: CtxDep,
) -> ApiResponse[List[schemas.KnowledgeSourceResponse]]:
    data = await service.list_knowledge_sources(
        db,
        tenant_id=ctx.tenant.id,
        chatbot_public_id=chatbot_id,
    )
    return ApiResponse(success=True, message="OK", data=data)


@router.patch(
    "/{tenant_public_id}/chatbots/{chatbot_id}/knowledge-sources/{ks_id}",
    response_model=ApiResponse[schemas.KnowledgeSourceResponse],
    summary="Update a knowledge source name or config",
)
async def update_knowledge_source(
    chatbot_id: str,
    ks_id: str,
    payload: schemas.KnowledgeSourceUpdateRequest,
    db: DBDep,
    ctx: CtxDep,
) -> ApiResponse[schemas.KnowledgeSourceResponse]:
    require_write(ctx)
    data = await service.update_knowledge_source(
        db,
        tenant_id=ctx.tenant.id,
        ks_public_id=ks_id,
        payload=payload,
    )
    return ApiResponse(success=True, message="Knowledge source updated.", data=data)


@router.delete(
    "/{tenant_public_id}/chatbots/{chatbot_id}/knowledge-sources/{ks_id}",
    response_model=ApiResponse[None],
    summary="Delete a knowledge source and all its data (crawl jobs, documents, chunks)",
)
async def delete_knowledge_source(
    chatbot_id: str,
    ks_id: str,
    db: DBDep,
    ctx: CtxDep,
) -> ApiResponse[None]:
    require_write(ctx)
    await service.delete_knowledge_source(
        db,
        tenant_id=ctx.tenant.id,
        ks_public_id=ks_id,
    )
    return ApiResponse(success=True, message="Knowledge source deleted.", data=None)


# =============================================================================
# CRAWL JOBS  (website source — submit URLs)
# =============================================================================


@router.post(
    "/{tenant_public_id}/chatbots/{chatbot_id}/knowledge-sources/{ks_id}/crawl-jobs",
    response_model=ApiResponse[List[schemas.CrawlJobResponse]],
    status_code=status.HTTP_201_CREATED,
    summary="Submit one or more URLs to crawl (queued as Celery task)",
)
async def submit_crawl_jobs(
    chatbot_id: str,
    ks_id: str,
    payload: schemas.CrawlJobCreateRequest,
    db: DBDep,
    ctx: CtxDep,
) -> ApiResponse[List[schemas.CrawlJobResponse]]:
    require_write(ctx)
    data = await service.submit_crawl_jobs(
        db,
        tenant_id=ctx.tenant.id,
        user_id=ctx.membership.user_id,
        ks_public_id=ks_id,
        payload=payload,
    )
    return ApiResponse(
        success=True,
        message=f"{len(data)} crawl job(s) queued.",
        data=data,
    )


@router.get(
    "/{tenant_public_id}/chatbots/{chatbot_id}/knowledge-sources/{ks_id}/crawl-jobs",
    response_model=ApiResponse[List[schemas.CrawlJobResponse]],
    summary="List crawl jobs for a knowledge source",
)
async def list_crawl_jobs(
    chatbot_id: str,
    ks_id: str,
    db: DBDep,
    ctx: CtxDep,
) -> ApiResponse[List[schemas.CrawlJobResponse]]:
    data = await service.list_crawl_jobs(
        db,
        tenant_id=ctx.tenant.id,
        ks_public_id=ks_id,
    )
    return ApiResponse(success=True, message="OK", data=data)


@router.post(
    "/{tenant_public_id}/chatbots/{chatbot_id}/knowledge-sources/{ks_id}/crawl-jobs/{job_public_id}/retry",
    response_model=ApiResponse[schemas.CrawlJobResponse],
    summary="Retry a failed or stuck crawl job",
)
async def retry_crawl_job(
    chatbot_id: str,
    ks_id: str,
    job_public_id: str,
    db: DBDep,
    ctx: CtxDep,
) -> ApiResponse[schemas.CrawlJobResponse]:
    require_write(ctx)

    job = await repo.get_crawl_job_by_public_id(db, tenant_id=ctx.tenant.id, public_id=job_public_id)
    if not job:
        raise HTTPException(status_code=404, detail="Crawl job not found.")

    if job.status == CrawlStatus.RUNNING:
        raise HTTPException(status_code=409, detail="Crawl job is already running.")

    ks = await repo.get_knowledge_source(db, tenant_id=ctx.tenant.id, source_id=job.knowledge_source_id)
    if not ks:
        raise HTTPException(status_code=404, detail="Knowledge source not found.")

    await repo.update_crawl_job(
        db, job=job,
        status=CrawlStatus.QUEUED,
        started_at=None,
        completed_at=None,
        error_message=None,
        pages_found=0,
        pages_processed=0,
        pages_failed=0,
    )
    await db.commit()
    await db.refresh(job)

    crawl_and_embed.apply_async(
        kwargs=dict(
            crawl_job_id=job.id,
            tenant_id=job.tenant_id,
            knowledge_source_id=job.knowledge_source_id,
            chatbot_config_id=ks.chatbot_config_id,
            base_url=job.base_url,
        ),
        queue=QUEUEEnum.ANALYSIS.value,
    )

    return ApiResponse(
        success=True,
        message="Crawl job re-queued.",
        data=schemas.CrawlJobResponse.model_validate(job),
    )


# =============================================================================
# DOCUMENTS  (document source — upload PDF / DOCX / TXT)
# =============================================================================

# Allowed MIME types → internal file_type key
_ALLOWED_MIME_TYPES: dict[str, str] = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/msword": "docx",
    "text/plain": "txt",
    "application/octet-stream": "pdf",  # fallback — infer from extension below
}


def _infer_file_type(filename: str, content_type: str) -> str:
    """Infer file_type from extension when content_type is octet-stream."""
    ext = (filename or "").rsplit(".", 1)[-1].lower()
    ext_map = {"pdf": "pdf", "docx": "docx", "doc": "docx", "txt": "txt"}
    if content_type == "application/octet-stream":
        return ext_map.get(ext, "pdf")
    return _ALLOWED_MIME_TYPES.get(content_type, "pdf")


@router.post(
    "/{tenant_public_id}/chatbots/{chatbot_id}/knowledge-sources/{ks_id}/documents",
    response_model=ApiResponse[schemas.DocumentResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Upload a document (PDF, DOCX, TXT) — parsed and embedded in the background",
)
async def upload_document(
    chatbot_id: str,
    ks_id: str,
    db: DBDep,
    ctx: CtxDep,
    file: UploadFile = File(..., description="PDF, DOCX, or TXT file"),
) -> ApiResponse[schemas.DocumentResponse]:
    require_write(ctx)

    content_type = file.content_type or "application/octet-stream"
    if content_type not in _ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"Unsupported file type '{content_type}'. "
                "Accepted: PDF, DOCX, DOC, TXT."
            ),
        )

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty.")

    if len(file_bytes) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the {settings.MAX_UPLOAD_MB} MB upload limit.",
        )

    file_type = _infer_file_type(file.filename or "", content_type)

    data = await service.upload_document(
        db,
        tenant_id=ctx.tenant.id,
        user_id=ctx.membership.user_id,
        ks_public_id=ks_id,
        file_name=file.filename or f"upload.{file_type}",
        file_type=file_type,
        file_size_bytes=len(file_bytes),
        file_data=file_bytes,
    )
    return ApiResponse(
        success=True,
        message="Document uploaded and queued for processing.",
        data=data,
    )


@router.get(
    "/{tenant_public_id}/chatbots/{chatbot_id}/knowledge-sources/{ks_id}/documents",
    response_model=ApiResponse[List[schemas.DocumentResponse]],
    summary="List documents for a knowledge source",
)
async def list_documents(
    chatbot_id: str,
    ks_id: str,
    db: DBDep,
    ctx: CtxDep,
) -> ApiResponse[List[schemas.DocumentResponse]]:
    data = await service.list_documents(
        db,
        tenant_id=ctx.tenant.id,
        ks_public_id=ks_id,
    )
    return ApiResponse(success=True, message="OK", data=data)


@router.get(
    "/{tenant_public_id}/chatbots/{chatbot_id}/knowledge-sources/{ks_id}/documents/{doc_id}/download",
    summary="Download or view an uploaded document",
    response_class=Response,
)
async def download_document(
    chatbot_id: str,
    ks_id: str,
    doc_id: str,
    db: DBDep,
    ctx: CtxDep,
    inline: bool = False,
) -> Response:
    """
    Serves the raw file bytes stored for an uploaded document.

    - `inline=false` (default) → browser downloads the file (Content-Disposition: attachment)
    - `inline=true`  → browser opens inline if it can (e.g. PDF viewer in a modal)

    Only user-uploaded documents (PDF, DOCX, TXT) have stored bytes.
    Crawled HTML pages return 422 — they have no downloadable file.
    """
    file_bytes, mime_type, file_name = await service.download_document(
        db,
        tenant_id=ctx.tenant.id,
        doc_public_id=doc_id,
    )

    disposition = "inline" if inline else "attachment"

    return Response(
        content=file_bytes,
        media_type=mime_type,
        headers={
            "Content-Disposition": f'{disposition}; filename="{file_name}"',
            "Content-Length": str(len(file_bytes)),
            # Prevent proxies from caching sensitive tenant documents
            "Cache-Control": "private, no-store",
        },
    )


# =============================================================================
# MANUAL Q&A ENTRIES  (manual_qa source)
# =============================================================================


@router.post(
    "/{tenant_public_id}/chatbots/{chatbot_id}/knowledge-sources/{ks_id}/manual-entries",
    response_model=ApiResponse[schemas.DocumentResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Add a manual Q&A / text entry — chunked and embedded in the background",
)
async def create_manual_entry(
    chatbot_id: str,
    ks_id: str,
    payload: schemas.ManualEntryCreateRequest,
    db: DBDep,
    ctx: CtxDep,
) -> ApiResponse[schemas.DocumentResponse]:
    require_write(ctx)
    data = await service.create_manual_entry(
        db,
        tenant_id=ctx.tenant.id,
        user_id=ctx.membership.user_id,
        ks_public_id=ks_id,
        payload=payload,
    )
    return ApiResponse(
        success=True,
        message="Entry queued for processing.",
        data=data,
    )


# =============================================================================
# LEGACY ENDPOINTS  (kept for backwards compatibility)
# =============================================================================


@router.post(
    "/embeddings/links_scrap",
    response_model=ApiResponse[schemas.liveLinkScrapperResponse],
    status_code=status.HTTP_200_OK,
    summary="[Legacy] Scrape a URL and return a Celery task ID",
)
async def legacy_link_scrapper(
    payload: schemas.liveLinkScrapperRequest,
    db: DBDep,
) -> ApiResponse[schemas.liveLinkScrapperResponse]:
    try:
        reply = await service.scrap_website_data(db, payload=payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception:
        logger.exception("Unexpected error in legacy_link_scrapper")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not process your request.",
        )
    return ApiResponse(success=True, message="Task queued.", data=reply)


@router.post(
    "/embeddings/pdf",
    summary="[Legacy] Parse a PDF from upload / URL / GCS / S3",
)
async def legacy_parse_pdf(
    source: str = Form(...),
    file: Optional[UploadFile] = File(default=None),
    path: Optional[str] = Form(default=None),
    extract_tables: bool = Form(default=True),
    password: Optional[str] = Form(default=None),
) -> JSONResponse:
    if source == "upload":
        if file is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="source='upload' requires a PDF file.",
            )
        if file.content_type not in ("application/pdf", "application/octet-stream"):
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"Expected a PDF, got '{file.content_type}'.",
            )
        pdf_bytes = await file.read()
        if not pdf_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is empty.",
            )
        result = _empty_result(file.filename or "upload.pdf", source="upload")
        try:
            result.update(
                _parse_pdf(pdf_bytes, extract_tables=extract_tables, password=password)
            )
        except Exception as exc:
            result["error"] = f"Parse error: {exc}"

    elif source in ("url", "gcs", "s3"):
        if not path:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"source='{source}' requires a 'path' form field.",
            )
        results = await read_pdf(
            path, source=source, extract_tables=extract_tables, password=password
        )
        result = results.get(path, _empty_result(_filename_from_path(path), source))
        if result.get("error"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=result["error"],
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown source '{source}'.",
        )

    return JSONResponse(content=result)
