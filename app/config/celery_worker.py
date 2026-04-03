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
   


celery_app = Celery(
    settings.APP_NAME,
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,

)

celery_app.conf.beat_schedule = {
    # Runs every hour at :00 — processes idle conversations
    "process-idle-conversations": {
        "task": "tasks.process_idle_conversations",
        "schedule": crontab(minute=0),  # top of every hour
    },

    # Runs every day at 8:00 AM — daily insight sweep
    "daily-insight-sweep": {
        "task": "tasks.daily_insight_sweep",
        "schedule": crontab(hour=8, minute=0),
    },

}
celery_app.autodiscover_tasks(
    ['app.modules.onboarding.tasks', 'app.modules.chat.tasks','app.modules.auth.tasks'])

celery_app.conf.broker_connection_retry_on_startup = True

if settings.ENV in ["PRODUCTION", "STAGING"]:
    import ssl
    celery_app.conf.broker_use_ssl = {"ssl_cert_reqs": ssl.CERT_NONE}
    celery_app.conf.redis_backend_use_ssl = {"ssl_cert_reqs": ssl.CERT_NONE}

celery_app.conf.update(
    task_track_started=settings.CELERY_TASK_TRACK_STARTED,
    task_serializer=settings.CELERY_TASK_SERIALIZER,
    result_expires=settings.CELERY_RESULT_EXPIRES,
    task_routes={
        # Scraping + file reading
        #"app.modules.onboarding.tasks": {"queue": "ingestion"},
        "app.modules.onboarding.tasks": {"queue": "ingestion"},

        # Embeddings
        "app.modules.chat.tasks": {"queue": "analysis"},

        # # Embeddings
        # "app.modules.onboarding.tasks": {"queue": "embedding"},
    },
)
