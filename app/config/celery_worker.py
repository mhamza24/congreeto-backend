from celery import Celery
from celery.schedules import crontab
import ssl
import os
from app.config.settings import get_settings
from enum import Enum

# Register all ORM models so SQLAlchemy mapper can resolve cross-module
# relationships (e.g. TenantSubscription → Tenant) before any task runs.
import app.modules.tenants.models      # noqa: F401
import app.modules.auth.models         # noqa: F401
import app.modules.users.models        # noqa: F401
import app.modules.billing.models      # noqa: F401
import app.modules.chatbot.models      # noqa: F401
import app.modules.chat.models         # noqa: F401
import app.modules.inquiries.models    # noqa: F401
import app.modules.audit.models        # noqa: F401

settings = get_settings()
os.environ.setdefault("FORKED_BY_MULTIPROCESSING", "1")


class QUEUEEnum(str, Enum):
    INGESTION = "ingestion"
    ANALYSIS = "analysis"


# ✅ Don't pass broker/backend in constructor — set via conf instead
celery_app = Celery(settings.APP_NAME)

ssl_config = {}
if settings.ENV in ["PRODUCTION", "STAGING"]:
    ssl_config = {"ssl_cert_reqs": ssl.CERT_NONE}

celery_app.conf.update(
    broker_url=settings.REDIS_URL,
    result_backend=settings.REDIS_URL,
    # ✅ SSL for rediss:// on Heroku
    broker_use_ssl=ssl_config if ssl_config else None,
    redis_backend_use_ssl=ssl_config if ssl_config else None,
    broker_connection_retry_on_startup=True,
    broker_connection_max_retries=None,  # retry forever on disconnect
    task_track_started=settings.CELERY_TASK_TRACK_STARTED,
    task_serializer=settings.CELERY_TASK_SERIALIZER,
    result_expires=settings.CELERY_RESULT_EXPIRES,
    task_default_queue=QUEUEEnum.ANALYSIS,
    task_routes={},
    # ── Redis connection resilience ───────────────────────────────────────
    # Keeps TCP connections alive through idle periods so long-running tasks
    # (crawl, embed) don't hit "Connection reset by peer" mid-execution.
    broker_transport_options={
        "socket_keepalive": True,
        "retry_on_timeout": True,
        "socket_connect_timeout": settings.REDIS_SOCKET_CONNECT_TIMEOUT,
        "socket_timeout": settings.REDIS_SOCKET_TIMEOUT,
        "health_check_interval": settings.REDIS_HEALTH_CHECK_INTERVAL,
    },
    redis_socket_timeout=settings.REDIS_SOCKET_TIMEOUT,
    redis_socket_connect_timeout=settings.REDIS_SOCKET_CONNECT_TIMEOUT,
    # ── Worker reliability ────────────────────────────────────────────────
    # Acknowledge only after the task finishes — safe to retry on worker crash.
    task_acks_late=True,
    # Re-queue the task if the worker process is killed while running it.
    task_reject_on_worker_lost=True,
    # Fetch one task at a time per worker process — prevents long tasks from
    # blocking other work and keeps Redis message throughput predictable.
    worker_prefetch_multiplier=1,
)

celery_app.conf.beat_schedule = {
    "process-idle-conversations": {
        "task": "tasks.process_idle_conversations",
        "schedule": crontab(minute=0),
    },
    "daily-insight-sweep": {
        "task": "tasks.daily_insight_sweep",
        "schedule": crontab(hour=8, minute=0),
    },
    # Billing
    "billing-reconcile-usage": {
        "task": "billing.reconcile_usage",
        "schedule": crontab(minute=0),           # every hour
    },
    "billing-check-usage-limits": {
        "task": "billing.check_usage_limits",
        "schedule": crontab(minute=10),          # 10 min after reconcile
    },
    "billing-reset-monthly-usage": {
        "task": "billing.reset_monthly_usage",
        "schedule": crontab(day_of_month=1, hour=0, minute=5),  # 1st of month 00:05 UTC
    },
    # Tenant lifecycle
    "tenants-expire-trials": {
        "task": "tenants.expire_trials",
        "schedule": crontab(minute=0),           # every hour
    },
    "tenants-sync-past-due": {
        "task": "tenants.sync_past_due_tenants",
        "schedule": crontab(minute=30),          # every hour at :30
    },
    # Crawl recovery
    "crawl-retry-stuck-jobs": {
        "task": "app.modules.chatbot.tasks.retry_stuck_crawl_jobs",
        "schedule": crontab(minute="*/10"),       # every 10 minutes
    },
    # Document recovery — re-queue FAILED or orphaned PROCESSING documents
    "chatbot-retry-failed-documents": {
        "task": "app.modules.chatbot.tasks.retry_failed_documents",
        "schedule": crontab(minute="*/15"),       # every 15 minutes
    },
}

celery_app.autodiscover_tasks(
    [
        "app.modules.chatbot.tasks",
        "app.modules.chat.tasks",
        "app.modules.auth.tasks",
        "app.modules.tenants.tasks",
        "app.modules.tenants.corn_tasks",
        "app.modules.billing.tasks",
    ]
)