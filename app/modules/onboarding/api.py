from __future__ import annotations

import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import ApiResponse
from app.modules.onboarding import schemas, service

from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse

from .parsers.pdf_parser import read_pdf, _parse_pdf, _empty_result, _filename_from_path
from app.config.settings import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/embeddings", tags=["Embedding"])


DBDep = Annotated[AsyncSession, Depends(get_db)]


@router.post(
    "/links_scrap",
    response_model=ApiResponse[schemas.liveLinkScrapperResponse],
    status_code=status.HTTP_200_OK,
    summary="Take links and scrap them for data",
)
async def chat_endpoint(
    payload: schemas.liveLinkScrapperRequest,
    db: DBDep,
) -> ApiResponse[schemas.liveLinkScrapperResponse]:
    try:
        reply = await service.scrap_website_data(
            db,
            payload=payload,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception:
        logger.exception("Unexpected error in chat_endpoint")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not process your request. Please try again later.",
        )

    return ApiResponse(
        success=True,
        message="Message processed successfully.",
        data=reply,
    )

@router.post(
    "/pdf",
    summary="Parse a PDF from any source",
    description="""
**One endpoint. Switch sources via the `source` field.**

| source   | required fields                        |
|----------|----------------------------------------|
| upload   | `file` (File)                          |
| url      | `path` (presigned or public blob URL)  |
| gcs      | `path` as `gs://bucket/file.pdf`       |
| s3       | `path` as `s3://bucket/file.pdf`       |

Optional fields for all sources: `extract_tables` (bool), `password` (str).
    """,
)
async def parse_pdf(
    source: str = Form(
        ...,
        description="'upload' | 'url' | 'gcs' | 's3'",
    ),
    file: Optional[UploadFile] = File(
        default=None,
        description="PDF binary — required when source='upload'.",
    ),
    path: Optional[str] = Form(
        default=None,
        description="URL or bucket path — required when source is url / gcs / s3.",
    ),
    extract_tables: bool = Form(default=True),
    password: Optional[str] = Form(default=None),
) -> JSONResponse:

    # ── Input validation ───────────────────────────────────────────────────
    if source == "upload":
        if file is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="source='upload' requires a PDF attached as form-data field 'file'.",
            )

    elif source in ("url", "gcs", "s3"):
        if not path:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"source='{source}' requires a 'path' form field.",
            )

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown source '{source}'. Must be 'upload', 'url', 'gcs', or 's3'.",
        )

    # ── Source: binary upload (Postman file / frontend FormData) ──────────
    if source == "upload":
        if file.content_type not in ("application/pdf", "application/octet-stream"):
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"Expected a PDF, got content-type '{file.content_type}'.",
            )

        # UploadFile.read() gives raw bytes — identical to what GCS / S3 return.
        # Same _parse_pdf() call runs for all sources from this point forward.
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

    # ── Source: URL / GCS / S3 ─────────────────────────────────────────────
    else:
        results = await read_pdf(
            path,
            source=source,
            extract_tables=extract_tables,
            password=password,
        )
        result = results.get(path, _empty_result(_filename_from_path(path), source))

        if result.get("error"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=result["error"],
            )

    return JSONResponse(content=result)
