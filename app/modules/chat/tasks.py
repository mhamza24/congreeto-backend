from sqlalchemy.ext.asyncio import AsyncSession
import asyncio
import json
from app.utils.system_prompt_chat_analysis import system_prompt_extract_chat_insights
from app.config.settings import get_settings
from app.config.celery_worker import celery_app, QUEUEEnum
from app.modules.open_ai import service as ai_service
import logging
from . import repository as repo
from .task_helper import run_analysis
logger = logging.getLogger(__name__)
settings = get_settings()
@celery_app.task
def background_analysis(conversation_id: str):
    print(f"Analyzing conversation {conversation_id}")


@celery_app.task(
    bind=True,
    name="app.modules.chat.tasks.chat_completion_task",
    max_retries=settings.CELERY_MAX_TRIES,
    default_retry_delay=settings.CELERY_DEFAULT_RETRY_DELAY,
    queue=QUEUEEnum.ANALYSIS.value,
)
def chat_completion_task(self, conversation__id: str, tenant_id: str):
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                run_analysis(conversation__id, tenant_id))
        finally:
            loop.close()
            asyncio.set_event_loop(None)

        return {"conversation__id": conversation__id, "result": result}
    except Exception as exc:
        countdown = min(300, 2 ** self.request.retries * 10)
        raise self.retry(exc=exc, countdown=countdown)
