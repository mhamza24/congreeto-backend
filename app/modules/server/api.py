from fastapi import APIRouter, status
from app.core.response import ApiResponse

router = APIRouter(prefix="/server", tags=["Server"])


@router.get("/health", response_model=ApiResponse[None], status_code=status.HTTP_200_OK,)
async def health_check():
    return ApiResponse(
        success=True,
        message="Veloce Server is healthy and running"
    )
