import os
from functools import lru_cache
from pydantic_settings import BaseSettings


ENV = os.getenv("ENV", "DEVELOPMENT")

ENV_FILES = {
    "DEVELOPMENT": ".env.development",
    "STAGING": ".env.staging",
    "PRODUCTION": ".env",
}


class Settings(BaseSettings):
    APP_NAME: str = "Veloce Backend"

    ENV: str
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    ALEMBIC_DATABASE_URL: str
    DATABASE_URL: str
    REDIS_URL: str

    RATE_LIMIT_REQUEST_COUNT: int = 100  # max requests
    RATE_LIMIT_WINDOW_SECONDS: int = 60  # per 60 seconds

    DOCS_USERNAME: str
    DOCS_PASSWORD: str

    JWT_SECRET: str
    JWT_ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int
    REFRESH_TOKEN_EXPIRE_DAYS: int

    IDENTITY_HASH_SALT: str
    PASSWORD_HASH_PEPPER: str
    PASSWORD_HASH_ROUND: int
    OTP_HASH_SALT: str

    OTP_EXPIRES_IN_MINUTES: int = 15
    OTP_MAX_ATTEMPTS: int = 5
    OTP_LOCKOUT_SECONDS: int = 86400  # 24 hours after max attempts

    CELERY_RESULT_EXPIRES: int = 18000
    CELERY_TASK_TRACK_STARTED: bool = True
    CELERY_TASK_SERIALIZER: str = "json"
    CELERY_USE_SSL: bool = False
    CELERY_DEFAULT_QUEUE: str = "default"
    CELERY_MAX_TRIES: int = 3
    CELERY_DEFAULT_RETRY_DELAY: int = 5

    OPEN_AI_KEY: str
    OPEN_AI_MODEL: str = "gpt-4.1"
    OPEN_AI_MAX_TOKENS: int = 800
    OPEN_AI_MAX_RETRIES: int = 3
    OPEN_AI_TIMEOUT: float = 30.0
    OPEN_AI_TEMPERATURE: float = 0.48
    OPEN_AI_TOP_P: float = 0.9
    OPEN_AI_FREQUENCY_PENALTY: float = 0.1
    OPEN_AI_PRESENCE_PENALTY: float = 0.1

    SCRAPPER_WEB_MAX_PAGES: int = 100
    SCRAPPER_WEB_HEADLESS: bool = True
    SCRAPPER_WEB_TIMEOUT: int = 30_000
    SCRAPPER_PDF_TIMEOUT: int = 30

    # Knowledge / document upload limits
    MAX_UPLOAD_MB: int = 50  # hard per-file cap regardless of plan

    MAIL_USERNAME: str
    MAIL_PASSWORD: str
    MAIL_FROM: str
    MAIL_SERVER: str = "smtp.office365.com"
    MAIL_PORT: int = 587

    SENTRY_DSN: str

    CHAT_IDLE_THRESHOLD_MINUTES: int = 15
    CHAT_IDLE_BATCH_SIZE: int = 100
    CHAT_PREVIOUS_CONVERSATION_SESSION_LIMIT: int = 5
    # Pagination defaults for the chat/conversation list API
    CHAT_PAGE_SIZE_DEFAULT: int = 20
    CHAT_PAGE_SIZE_MAX: int = 100

    DEFAULT_SEAT_LIMIT: int = 3

    FRONTEND_URL: str = "http://localhost:3000"

    # ── Internal inquiry email recipients ─────────────────────────────────────
    # Comma-separated list of Veloce team emails that receive contact / demo /
    # affiliation form submissions.  Never expose these to tenants.
    INQUIRY_RECIPIENTS: str = "contact@getveloce.com"

    # ── Chat conversation ─────────────────────────────────────────────────────
    # Max messages loaded from history for each LLM context window.
    CHAT_HISTORY_LIMIT: int = 50

    # ── Billing defaults ──────────────────────────────────────────────────────
    # Fallback limits used when no plan-level override exists.
    BILLING_DEFAULT_MAX_TOKENS_PER_MONTH: int = 1_000_000
    BILLING_DEFAULT_MAX_CONVERSATIONS_PER_MONTH: int = 750

    # ── RAG retrieval ─────────────────────────────────────────────────────────
    # Number of knowledge-base chunks injected into each LLM call.
    RAG_TOP_K: int = 10
    # Number of listing slots injected alongside RAG chunks.
    RAG_LISTING_TOP_K: int = 8

    # ── Knowledge ingestion pipeline ─────────────────────────────────────────
    # Word-based chunking for crawled pages and uploaded documents.
    CHUNK_SIZE: int = 500         # max words per chunk
    CHUNK_OVERLAP: int = 50       # word overlap between adjacent chunks
    # Max texts per OpenAI embeddings API call (API hard limit is 2048).
    EMBED_BATCH_SIZE: int = 100
    # Max output tokens for listing extraction LLM calls.
    LLM_EXTRACT_MAX_TOKENS: int = 1500
    # Rows sent to the LLM per batch when parsing Excel/CSV listing files.
    LLM_FILE_PARSE_BATCH_SIZE: int = 20
    # Listings per embed_listings_batch Celery task dispatch.
    CRAWL_LISTING_EMBED_BATCH_SIZE: int = 100
    # Documents that have been FAILED/PROCESSING for this many minutes
    # will be picked up by the retry_failed_documents beat task.
    STALE_DOCUMENT_THRESHOLD_MINUTES: int = 10

    # ── Celery / Redis transport ───────────────────────────────────────────────
    REDIS_SOCKET_TIMEOUT: int = 120
    REDIS_SOCKET_CONNECT_TIMEOUT: int = 10
    REDIS_HEALTH_CHECK_INTERVAL: int = 25

    class Config:
        env_file = ENV_FILES.get(ENV, ".env.development")


@lru_cache
def get_settings():
    return Settings()
