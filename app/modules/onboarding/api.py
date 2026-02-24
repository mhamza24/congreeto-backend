from __future__ import annotations

import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import ApiResponse
from app.modules.onboarding import schemas, service

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
