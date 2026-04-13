from fastapi import APIRouter, Depends, status
from typing import Dict, Any
from sqlalchemy import text
from app.core.response import ApiResponse
from app.config.settings import get_settings
from app.core.docs import verify_docs_credentials
import logging

settings = get_settings()
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/server", tags=["Server"])


@router.get(
    "/health",
    response_model=ApiResponse[Dict[str, Any]],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(verify_docs_credentials)],
    summary="Comprehensive health check — database, Redis, and application status",
)
async def health_check():
    """
    Returns the health of all core dependencies.
    Requires HTTP Basic Auth (same credentials as /docs).
    Overall status is 'healthy' when all checks pass, 'degraded' when any fail.
    """
    logger.info("[health] health check requested env=%s", settings.ENV)
    checks: Dict[str, Any] = {}
    overall = "healthy"

    # ── Database ──────────────────────────────────────────────────────────
    try:
        from app.core.database import async_engine
        async with async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = {"status": "healthy"}
        logger.debug("[health] database check passed")
    except Exception as exc:
        checks["database"] = {"status": "unhealthy", "detail": str(exc)}
        overall = "degraded"
        logger.error("[health] database check failed error=%s", exc)

    # ── Redis ─────────────────────────────────────────────────────────────
    try:
        from app.core.redis import redis_client
        await redis_client.ping()
        checks["redis"] = {"status": "healthy"}
        logger.debug("[health] redis check passed")
    except Exception as exc:
        checks["redis"] = {"status": "unhealthy", "detail": str(exc)}
        overall = "degraded"
        logger.error("[health] redis check failed error=%s", exc)

    # ── Application ───────────────────────────────────────────────────────
    checks["application"] = {
        "status": "healthy",
        "name": settings.APP_NAME,
        "environment": settings.ENV,
    }

    logger.info("[health] check complete overall=%s", overall)
    return ApiResponse(
        success=True,
        message="Health check complete.",
        data={
            "status": overall,
            "environment": settings.ENV,
            "checks": checks,
        },
    )


@router.get("/sentry-debug")
async def trigger_error():
    division_by_zero = 1 / 0
