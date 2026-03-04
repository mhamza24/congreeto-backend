from fastapi import APIRouter, Depends, HTTPException, Query, status
from typing import Dict, Any
from app.core.database import get_db
from app.core.response import ApiResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.dashboard import schemas
from app.modules.dashboard import service
from typing import Annotated, Optional
from app.modules.email import service as email_service

import logging
logger = logging.getLogger(__name__)


router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


async def get_tenant_id(tenant_id: str | None = Query(default=None)) -> str:
    """
    Extract tenant_id from query param (?tenant_id=xxx).
    Falls back to "veloce" if not provided.
    Replace with real auth logic when ready.
    """
    return tenant_id or "veloce"
TenantDep = Annotated[str, Depends(get_tenant_id)]
DBDep = Annotated[AsyncSession, Depends(get_db)]


@router.get("/summary",
            response_model=ApiResponse[schemas.DashboardSummaryResponse],
            status_code=status.HTTP_200_OK,)
async def get_summary(#payload: schemas.DashboardSummaryRequest,
                      db: DBDep, tenant_id: TenantDep):
    try:
        result = await service.fetch_summary(
            db,
           # payload=payload,
           tenant_id=tenant_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception:
        logger.exception("Unexpected error in dashboard summary endpoint")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not fetch dashboard summary. Please try again later.",
        )

    return ApiResponse(
        success=True,
        message="Dashboard summary fetched successfully.",
        data=result,
    )
