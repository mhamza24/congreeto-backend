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
from .task_helper import run_analysis,_fetch_idle_conversations


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


# ──────────────────────────────────────────────────────────────
# Beat task  — runs every hour, spawns one child per idle convo
# ──────────────────────────────────────────────────────────────

@celery_app.task(
    name="tasks.process_idle_conversations",   # must match beat_schedule key
    queue=QUEUEEnum.ANALYSIS.value,
)
def process_idle_conversations():
    """
    Cron job (every hour) — finds all in_progress conversations that have
    been idle for >= IDLE_THRESHOLD_MINUTES and spawns a chat_completion_task
    for each one.

    Covers both `website` and `veloce_demo` chatbot identities since the
    existing chat_completion_task / run_analysis handles both contexts.

    Safe to re-run: the repository query only returns `in_progress`
    conversations, so any conversation already being processed (status
    updated to `summarized` mid-run) will be skipped automatically.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        idle_conversations = loop.run_until_complete(
            _fetch_idle_conversations())
    finally:
        loop.close()
        asyncio.set_event_loop(None)

    if not idle_conversations:
        logger.info("[idle-cron] No idle conversations found.")
        return {"spawned": 0}

    spawned = 0
    for conversation_id, tenant_id in idle_conversations:
        try:
            # Reuse the exact same task that fires on manual chat close.
            # Each conversation gets its own worker slot — parallel + isolated.
            chat_completion_task.apply_async(
                kwargs={
                    "conversation__id": conversation_id,
                    "tenant_id":        tenant_id,
                },
                queue=QUEUEEnum.ANALYSIS.value,
            )
            spawned += 1
            logger.info(
                f"[idle-cron] Spawned analysis for "
                f"conversation_id={conversation_id} tenant={tenant_id}"
            )
        except Exception as exc:
            # Log and continue — one bad spawn must not block the rest
            logger.error(
                f"[idle-cron] Failed to spawn task for "
                f"conversation_id={conversation_id}: {exc}",
                exc_info=True,
            )

    logger.info(f"[idle-cron] Done. Spawned {spawned} task(s).")
    return {"spawned": spawned}


