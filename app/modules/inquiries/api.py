from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
import sentry_sdk
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import ApiResponse
from app.modules.inquiries import schemas, service
from app.modules.inquiries.models import InquiryStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/inquiries", tags=["Inquiries"])

DBDep = Annotated[AsyncSession, Depends(get_db)]


@router.post(
    "/general",
    response_model=ApiResponse[schemas.GeneralInquiryResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Create a new general inquiry",
)
async def create_general_inquiry(
    payload: schemas.GeneralInquiryCreateRequest,
    db: DBDep,
) -> ApiResponse[schemas.GeneralInquiryResponse]:
    try:
        inquiry = await service.create_general(db, payload)
    except Exception as exc:
        logger.exception("Unexpected error in create_general_inquiry")
        sentry_sdk.capture_exception(exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create inquiry. Please try again later.",
        )

    return ApiResponse(
        success=True,
        message="General inquiry created and emails sent successfully.",
        data=inquiry,
    )
    
    
@router.post(
    "/demo",
    response_model=ApiResponse[schemas.DemoInquiryResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Create a new demo inquiry",
)
async def create_demo_inquiry(
    payload: schemas.DemoInquiryCreateRequest,
    db: DBDep,
) -> ApiResponse[schemas.DemoInquiryResponse]:
    try:
        demo_inquiry = await service.create_demo(db, payload)
    except Exception as exc:
        logger.exception("Unexpected error in create_demo_inquiry")
        sentry_sdk.capture_exception(exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create demo inquiry. Please try again later.",
        )

    return ApiResponse(
        success=True,
        message="Demo inquiry created and emails sent successfully.",
        data=demo_inquiry,
    )