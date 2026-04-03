from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi import HTTPException
from fastapi.params import Depends
from app.config.sentry import init_sentry
from app.core import exceptions
from app.config.logging import setup_logging
from app.config.rate_limit import RateLimitMiddleware
from app.api.v1.router import router as v1_router
from fastapi import APIRouter
from app.config.settings import Settings
import logging
from app.config.settings import get_settings
from app.core.docs import verify_docs_credentials
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.openapi.utils import get_openapi

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
    title=settings.APP_NAME,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

if ENVIRONMENT != "PRODUCTION":

    @app.get("/docs", include_in_schema=False)
    async def get_docs(credentials=Depends(verify_docs_credentials)):
        return get_swagger_ui_html(
            openapi_url="/openapi.json",
            title=f"{settings.APP_NAME} - Docs",
            swagger_js_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist/swagger-ui-bundle.js",
            swagger_css_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist/swagger-ui.css",
        )

    @app.get("/redoc", include_in_schema=False)
    async def get_redoc(credentials=Depends(verify_docs_credentials)):
        return get_redoc_html(
            openapi_url="/openapi.json",
            title=f"{settings.APP_NAME} - Redoc",
            redoc_js_url="https://cdn.jsdelivr.net/npm/redoc/bundles/redoc.standalone.js",
        )

    @app.get("/openapi.json", include_in_schema=False)
    async def get_openapi_json(credentials=Depends(verify_docs_credentials)):
        return get_openapi(
            title=app.title,
            version=app.version,
            routes=app.routes,
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)