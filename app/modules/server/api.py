from fastapi import APIRouter, status
from typing import Dict, Any
from app.core.response import ApiResponse
import logging
logger = logging.getLogger(__name__)



router = APIRouter(prefix="/server", tags=["Server"])


@router.get("/health", response_model=ApiResponse[Dict[str, str]], status_code=status.HTTP_200_OK,)
async def health_check():
    logger.info("Health check endpoint called")
    return ApiResponse(
        success=True,
        message="Veloce Server is healthy and running",
        data={
            "status": "healthy"
        }
    )
    
@router.get("/sentry-debug")
async def trigger_error():
    division_by_zero = 1 / 0
