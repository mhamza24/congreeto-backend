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

    CELERY_RESULT_EXPIRES: int = 3600   # 1 hour — results only needed briefly for status polling
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

    SCRAPPER_WEB_MAX_PAGES: int = 200
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

    # ── Pagination defaults (cursor / keyset paginated lists) ────────────────
    # All paginated endpoints accept ?page_size= bounded by these knobs.
    # Centralised so a single change here propagates everywhere.
    AUDIT_PAGE_SIZE_DEFAULT:        int = 50
    AUDIT_PAGE_SIZE_MAX:            int = 500
    DASHBOARD_LEADS_PAGE_SIZE_DEFAULT:      int = 10
    DASHBOARD_LEADS_PAGE_SIZE_MAX:          int = 100
    DASHBOARD_TENANTS_PAGE_SIZE_DEFAULT:    int = 50
    DASHBOARD_TENANTS_PAGE_SIZE_MAX:        int = 200
    LISTINGS_PAGE_SIZE_DEFAULT:     int = 20
    LISTINGS_PAGE_SIZE_MAX:         int = 200
    LISTING_UPLOAD_JOBS_PAGE_SIZE_DEFAULT:  int = 20
    LISTING_UPLOAD_JOBS_PAGE_SIZE_MAX:      int = 100
    CAMPAIGNS_PAGE_SIZE_DEFAULT:    int = 20
    CAMPAIGNS_PAGE_SIZE_MAX:        int = 100

    # ── Tenant invites ────────────────────────────────────────────────────────
    TENANT_INVITE_TTL_HOURS: int = 72   # Invite link / OTP validity window

    # ── TenantContext Redis cache ─────────────────────────────────────────────
    # TTL for caching tenant/membership/subscription IDs per authenticated request.
    # Reduces DB round-trips from 3 → 3 fast PK lookups on cache hit.
    TENANT_CONTEXT_CACHE_TTL: int = 60  # seconds

    # ── Chatbot assets ────────────────────────────────────────────────────────
    # Per-image upload cap for logos / avatars / banners (MB).
    CHATBOT_ASSET_MAX_MB:                int = 5
    # Browser/CDN cache TTL when serving widget assets (seconds). 24h default.
    CHATBOT_ASSET_CACHE_MAX_AGE_SECONDS: int = 86_400

    # ── OpenAI concurrency / model ────────────────────────────────────────────
    # Max concurrent embedding API calls per worker — keep inside OpenAI RPM limits.
    OPENAI_EMBED_CONCURRENCY: int = 5
    # Embedding model used for vector search (must match Vector(N) dim in models).
    OPENAI_EMBEDDING_MODEL:   str = "text-embedding-3-small"

    # ── OpenAI circuit breaker ────────────────────────────────────────────────
    # Consecutive transient failures (connection, timeout, 5xx) before the
    # breaker opens and stops sending requests to OpenAI.
    OPENAI_CIRCUIT_FAILURE_THRESHOLD: int = 5
    # Seconds to wait in OPEN state before probing with one request (HALF_OPEN).
    OPENAI_CIRCUIT_RECOVERY_TIMEOUT:  int = 60
    # Consecutive successes in HALF_OPEN needed to close the breaker again.
    OPENAI_CIRCUIT_HALF_OPEN_SUCCESSES: int = 2

    # ── Listing import pipeline ───────────────────────────────────────────────
    # Listings committed per DB transaction inside the import worker.
    LISTING_FILE_DB_BATCH_SIZE: int = 20

    # ── Billing fallback limits (used when plan has no value for the key) ────
    # Extends the BILLING_DEFAULT_* knobs above with per-resource fallbacks.
    BILLING_DEFAULT_MAX_PAGES_CRAWLED:       int = 200
    BILLING_DEFAULT_MAX_DOCUMENTS:           int = 120
    BILLING_DEFAULT_MAX_TOKENS_PER_CONVERSATION: int = 4_000

    # ── Stripe (placeholders — swap with real keys from dashboard.stripe.com) ─
    # Test mode for development. Production ENV must override these.
    # Keys live in your Stripe dashboard under Developers → API Keys.
    STRIPE_SECRET_KEY:      str = "sk_test_REPLACE_ME"
    STRIPE_PUBLISHABLE_KEY: str = "pk_test_REPLACE_ME"
    # Webhook signing secret is unique per webhook endpoint registered in
    # Stripe dashboard → Developers → Webhooks. Leave as REPLACE_ME during
    # local dev unless you've wired the Stripe CLI forward.
    STRIPE_WEBHOOK_SECRET:  str = "whsec_REPLACE_ME"
    # API version pin — Stripe rolls SDK changes by date. Pinning keeps our
    # webhook payload assumptions stable across SDK upgrades.
    STRIPE_API_VERSION:     str = "2024-06-20"
    # Where Stripe sends the user back after Checkout. Use {CHECKOUT_SESSION_ID}
    # placeholder so we can verify the session server-side on success.
    STRIPE_CHECKOUT_SUCCESS_URL: str = "https://veloce-dashboard-client.vercel.app/billing/success?session_id={CHECKOUT_SESSION_ID}"
    STRIPE_CHECKOUT_CANCEL_URL:  str = "https://veloce-dashboard-client.vercel.app/billing/cancelled"
    STRIPE_PORTAL_RETURN_URL:    str = "https://veloce-dashboard-client.vercel.app/billing"
    # Webhook event idempotency — how long to remember a processed event id.
    # Stripe replays events for up to ~3 days; 7d gives a safety margin.
    STRIPE_WEBHOOK_IDEMPOTENCY_TTL_SECONDS: int = 7 * 24 * 60 * 60
    # Default trial window applied when activating a NEW subscription via
    # Checkout. Set to 0 to disable trials entirely (charge immediately).
    STRIPE_DEFAULT_TRIAL_DAYS: int = 0

    FRONTEND_URL: str = "https://veloce-dashboard-client.vercel.app" #"https://kh-dashboard-seven.vercel.app" #"http://localhost:3000"

    # ── CORS ──────────────────────────────────────────────────────────────────
    # Comma-separated list of allowed origins.
    # Example: "https://app.getveloce.com,https://admin.getveloce.com"
    ALLOWED_ORIGINS: str = "*"

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
    # KB chunks injected per LLM call. 8 × 300-word chunks ≈ 1 800 tokens of
    # context — precise enough for real estate Q&A without bloating the prompt.
    RAG_TOP_K: int = 8
    # Listing slots injected alongside KB chunks. 5 is enough to show variety
    # without overwhelming the visitor or the LLM context window.
    RAG_LISTING_TOP_K: int = 5

    # ── Knowledge ingestion pipeline ─────────────────────────────────────────
    # Word-based chunking for crawled pages and uploaded documents.
    # 300 words (~225 tokens) is the sweet spot for real estate content:
    #   - Short listing pages (200-400 words) → 1 focused chunk each
    #   - Longer PDFs/guides split into precise retrievable units
    #   - Well under OpenAI's 8 192-token per-input embedding limit
    CHUNK_SIZE: int = 300         # max words per chunk
    # 50-word overlap = ~17% of chunk size — prevents cutting sentences at
    # boundaries without duplicating too much content.
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
