from celery import Celery
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
celery_app.autodiscover_tasks(
    ['app.modules.onboarding.tasks', 'app.modules.chat.tasks'])



if settings.ENV in ["PRODUCTION"]:
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
