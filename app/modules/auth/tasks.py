from sqlalchemy.ext.asyncio import AsyncSession
import asyncio
import json

from celery.schedules import crontab
from app.utils.system_prompt_chat_analysis import system_prompt_extract_chat_insights
from app.config.settings import get_settings
from app.core.database import get_task_db_session
from app.config.celery_worker import celery_app, QUEUEEnum
from app.modules.open_ai import service as ai_service
import logging
from . import repository as repo
from .task_helper import send_otp_verification_email_helper


logger = logging.getLogger(__name__)
settings = get_settings()


@celery_app.task(
    bind=True,
    name="app.modules.auth.tasks.send_otp_verification_email_task",
    max_retries=settings.CELERY_MAX_TRIES,
    default_retry_delay=settings.CELERY_DEFAULT_RETRY_DELAY,
    queue=QUEUEEnum.ANALYSIS.value,
)
def send_otp_verification_email_task(self, email: str, first_name: str, otp_code: int):
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                send_otp_verification_email_helper(email=email, first_name=first_name, otp_code=otp_code))
        finally:
            loop.close()
            asyncio.set_event_loop(None)

        return {"email": email, "result": result}
    except Exception as exc:
        countdown = min(300, 2 ** self.request.retries * 10)
        raise self.retry(exc=exc, countdown=countdown)
