from celery import Celery
from celery.schedules import crontab
import ssl
import os
from app.config.settings import get_settings
from enum import Enum

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
    task_track_started=settings.CELERY_TASK_TRACK_STARTED,
    task_serializer=settings.CELERY_TASK_SERIALIZER,
    result_expires=settings.CELERY_RESULT_EXPIRES,
    task_routes={
        "app.modules.knowledge.tasks": {"queue": "ingestion"},
        "app.modules.chat.tasks": {"queue": "analysis"},
    },
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
}

celery_app.autodiscover_tasks([
    'app.modules.knowledge.tasks',
    'app.modules.chat.tasks',
    'app.modules.auth.tasks',
    'app.modules.tenants.tasks',
    'app.modules.tenants.corn_tasks',
    'app.modules.billing.tasks',
])