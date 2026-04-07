"""
app/modules/knowledge/router.py

All routes are tenant-scoped. Tenant + user extracted from auth dependency.
Structure:

  POST   /chatbots                                          → create chatbot
  GET    /chatbots                                          → list chatbots
  GET    /chatbots/{chatbot_id}                             → get chatbot
  PATCH  /chatbots/{chatbot_id}                             → update chatbot
  POST   /chatbots/{chatbot_id}/activate                    → go live check + activate

  POST   /chatbots/{chatbot_id}/knowledge-sources           → create source
  GET    /chatbots/{chatbot_id}/knowledge-sources           → list sources

  POST   /chatbots/{chatbot_id}/knowledge-sources/{ks_id}/crawl-jobs   → submit URLs
  GET    /chatbots/{chatbot_id}/knowledge-sources/{ks_id}/crawl-jobs   → list jobs

  POST   /chatbots/{chatbot_id}/knowledge-sources/{ks_id}/documents    → upload PDF
  GET    /chatbots/{chatbot_id}/knowledge-sources/{ks_id}/documents    → list docs

  POST   /embeddings/links_scrap                            → legacy scrapper
  POST   /embeddings/pdf                                    → legacy PDF parser
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
    Path,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import ApiResponse
from app.modules.knowledge import schemas, service
from app.modules.knowledge.parsers.pdf_parser import (
    _empty_result,
    _filename_from_path,
    _parse_pdf,
    read_pdf,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledge",tags=["Knowledge"])

DBDep = Annotated[AsyncSession, Depends(get_db)]


# ---------------------------------------------------------------------------
# Auth stub — replace with your real dependency
# ---------------------------------------------------------------------------
def get_current_tenant_and_user() -> dict:
    """
    Replace this with your real auth dependency that returns:
    {"tenant_id": int, "user_id": int}
    """
    return {"tenant_id": 1, "user_id": 1}


AuthDep = Annotated[dict, Depends(get_current_tenant_and_user)]


# =============================================================================
# CHATBOT CONFIG
# =============================================================================

@router.post(
    "/chatbots",
    response_model=ApiResponse[schemas.ChatbotResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Create a new chatbot (also creates a default widget theme)",
)
async def create_chatbot(
    payload: schemas.ChatbotCreateRequest,
    db: DBDep,
    auth: AuthDep,
) -> ApiResponse[schemas.ChatbotResponse]:
    data = await service.create_chatbot(
        db,
        tenant_id=auth["tenant_id"],
        payload=payload,
    )
    return ApiResponse(success=True, message="Chatbot created.", data=data)


@router.get(
    "/chatbots",
    response_model=ApiResponse[List[schemas.ChatbotResponse]],
    summary="List all chatbots for the tenant",
)
async def list_chatbots(
    db: DBDep,
    auth: AuthDep,
) -> ApiResponse[List[schemas.ChatbotResponse]]:
    data = await service.list_chatbots(db, tenant_id=auth["tenant_id"])
    return ApiResponse(success=True, message="OK", data=data)


@router.get(
    "/chatbots/{chatbot_id}",
    response_model=ApiResponse[schemas.ChatbotResponse],
    summary="Get a single chatbot",
)
async def get_chatbot(
    chatbot_id: str,
    db: DBDep,
    auth: AuthDep,
) -> ApiResponse[schemas.ChatbotResponse]:
    data = await service.get_chatbot(
        db, tenant_id=auth["tenant_id"], public_id=chatbot_id
    )
    return ApiResponse(success=True, message="OK", data=data)


@router.patch(
    "/chatbots/{chatbot_id}",
    response_model=ApiResponse[schemas.ChatbotResponse],
    summary="Update chatbot settings",
)
async def update_chatbot(
    chatbot_id: str,
    payload: schemas.ChatbotUpdateRequest,
    db: DBDep,
    auth: AuthDep,
) -> ApiResponse[schemas.ChatbotResponse]:
    data = await service.update_chatbot(
        db,
        tenant_id=auth["tenant_id"],
        public_id=chatbot_id,
        payload=payload,
    )
    return ApiResponse(success=True, message="Chatbot updated.", data=data)


@router.post(
    "/chatbots/{chatbot_id}/activate",
    response_model=ApiResponse[schemas.ChatbotResponse],
    summary="Activate chatbot — validates that knowledge sources are ready",
)
async def activate_chatbot(
    chatbot_id: str,
    db: DBDep,
    auth: AuthDep,
) -> ApiResponse[schemas.ChatbotResponse]:
    data = await service.activate_chatbot(
        db, tenant_id=auth["tenant_id"], public_id=chatbot_id
    )
    return ApiResponse(success=True, message="Chatbot is now active.", data=data)


# =============================================================================
# KNOWLEDGE SOURCES
# =============================================================================

@router.post(
    "/chatbots/{chatbot_id}/knowledge-sources",
    response_model=ApiResponse[schemas.KnowledgeSourceResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Create a knowledge source (website | document | manual_qa)",
)
async def create_knowledge_source(
    chatbot_id: str,
    payload: schemas.KnowledgeSourceCreateRequest,
    db: DBDep,
    auth: AuthDep,
) -> ApiResponse[schemas.KnowledgeSourceResponse]:
    data = await service.create_knowledge_source(
        db,
        tenant_id=auth["tenant_id"],
        chatbot_public_id=chatbot_id,
        payload=payload,
    )
    return ApiResponse(success=True, message="Knowledge source created.", data=data)


@router.get(
    "/chatbots/{chatbot_id}/knowledge-sources",
    response_model=ApiResponse[List[schemas.KnowledgeSourceResponse]],
    summary="List knowledge sources for a chatbot",
)
async def list_knowledge_sources(
    chatbot_id: str,
    db: DBDep,
    auth: AuthDep,
) -> ApiResponse[List[schemas.KnowledgeSourceResponse]]:
    data = await service.list_knowledge_sources(
        db,
        tenant_id=auth["tenant_id"],
        chatbot_public_id=chatbot_id,
    )
    return ApiResponse(success=True, message="OK", data=data)


# =============================================================================
# CRAWL JOBS  (Option A — paste URLs)
# =============================================================================

@router.post(
    "/chatbots/{chatbot_id}/knowledge-sources/{ks_id}/crawl-jobs",
    response_model=ApiResponse[List[schemas.CrawlJobResponse]],
    status_code=status.HTTP_201_CREATED,
    summary="Submit one or more URLs to crawl",
)
async def submit_crawl_jobs(
    chatbot_id: str,
    ks_id: int,
    payload: schemas.CrawlJobCreateRequest,
    db: DBDep,
    auth: AuthDep,
) -> ApiResponse[List[schemas.CrawlJobResponse]]:
    data = await service.submit_crawl_jobs(
        db,
        tenant_id=auth["tenant_id"],
        user_id=auth["user_id"],
        knowledge_source_id=ks_id,
        payload=payload,
    )
    return ApiResponse(
        success=True,
        message=f"{len(data)} crawl job(s) queued.",
        data=data,
    )


@router.get(
    "/chatbots/{chatbot_id}/knowledge-sources/{ks_id}/crawl-jobs",
    response_model=ApiResponse[List[schemas.CrawlJobResponse]],
    summary="List crawl jobs for a knowledge source",
)
async def list_crawl_jobs(
    chatbot_id: str,
    ks_id: int,
    db: DBDep,
    auth: AuthDep,
) -> ApiResponse[List[schemas.CrawlJobResponse]]:
    data = await service.list_crawl_jobs(
        db,
        tenant_id=auth["tenant_id"],
        knowledge_source_id=ks_id,
    )
    return ApiResponse(success=True, message="OK", data=data)


# =============================================================================
# DOCUMENTS  (Option B — upload PDF)
# =============================================================================

@router.post(
    "/chatbots/{chatbot_id}/knowledge-sources/{ks_id}/documents",
    response_model=ApiResponse[schemas.DocumentResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Upload a PDF document — starts processing immediately",
)
async def upload_document(
    chatbot_id: str,
    ks_id: int,
    db: DBDep,
    auth: AuthDep,
    file: UploadFile = File(..., description="PDF file to upload"),
) -> ApiResponse[schemas.DocumentResponse]:
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

    data = await service.upload_document(
        db,
        tenant_id=auth["tenant_id"],
        user_id=auth["user_id"],
        knowledge_source_id=ks_id,
        file_name=file.filename or "upload.pdf",
        file_type="pdf",
        file_size_bytes=len(pdf_bytes),
        file_data=pdf_bytes,  # stored as blob; swap for S3 key later
    )
    return ApiResponse(success=True, message="Document uploaded and queued for processing.", data=data)


@router.get(
    "/chatbots/{chatbot_id}/knowledge-sources/{ks_id}/documents",
    response_model=ApiResponse[List[schemas.DocumentResponse]],
    summary="List documents for a knowledge source",
)
async def list_documents(
    chatbot_id: str,
    ks_id: int,
    db: DBDep,
    auth: AuthDep,
) -> ApiResponse[List[schemas.DocumentResponse]]:
    data = await service.list_documents(
        db,
        tenant_id=auth["tenant_id"],
        knowledge_source_id=ks_id,
    )
    return ApiResponse(success=True, message="OK", data=data)


# =============================================================================
# LEGACY ENDPOINTS  (kept from original router)
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
            result.update(_parse_pdf(pdf_bytes, extract_tables=extract_tables, password=password))
        except Exception as exc:
            result["error"] = f"Parse error: {exc}"

    elif source in ("url", "gcs", "s3"):
        if not path:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"source='{source}' requires a 'path' form field.",
            )
        results = await read_pdf(path, source=source, extract_tables=extract_tables, password=password)
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