from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi import HTTPException
from app.config.sentry import init_sentry
from app.core import exceptions
from app.config.logging import setup_logging
from app.config.rate_limit import RateLimitMiddleware
from app.api.v1.router import router as v1_router
from fastapi import APIRouter
from app.config.settings import Settings
import logging
from app.config.settings import get_settings

settings = get_settings()

logger = logging.getLogger(__name__)

setup_logging()

ENVIRONMENT = Settings().ENV


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Application startup")
    yield
    logger.info("🛑 Application shutdown")


app = FastAPI(
    lifespan=lifespan,
    docs_url=None if ENVIRONMENT == "PRODUCTION" else "/docs",
    redoc_url=None if ENVIRONMENT == "PRODUCTION" else "/redoc",
    openapi_url=None if ENVIRONMENT == "PRODUCTION" else "/openapi.json",
    title=settings.APP_NAME,
)

init_sentry()

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(RateLimitMiddleware)
# Register exception handlers
app.add_exception_handler(HTTPException, exceptions.http_exception_handler)
app.add_exception_handler(RequestValidationError,
                          exceptions.validation_exception_handler)

# Register API Router
app.include_router(v1_router, prefix="/api/v1")
