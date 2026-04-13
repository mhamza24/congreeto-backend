from app.core.database import get_db, get_task_db_session
import asyncio
import json
from datetime import datetime, timezone, timedelta
from app.utils.system_prompt_chat_analysis import system_prompt_extract_chat_insights, system_prompt_veloce_website_insights
from app.config.settings import get_settings
from app.config.celery_worker import celery_app, QUEUEEnum
from app.modules.open_ai import service as ai_service
from app.modules.chat import schemas as chat_schema
from app.modules.email import service as email_service
import logging
from . import repository as repo
import logging

settings = get_settings()
logger = logging.getLogger(__name__)

IDLE_THRESHOLD_MINUTES = settings.CHAT_IDLE_THRESHOLD_MINUTES
CHAT_IDLE_BATCH_SIZE = settings.CHAT_IDLE_BATCH_SIZE


async def _dispatch_in_batches() -> int:
    from app.modules.chat.tasks import chat_completion_task
    idle_before = datetime.now(timezone.utc) - \
        timedelta(minutes=IDLE_THRESHOLD_MINUTES)
    last_id = 0
    total_spawned = 0
    batch_count = 0

    logger.info("[idle-cron] _dispatch_in_batches started idle_threshold_minutes=%d", IDLE_THRESHOLD_MINUTES)

    while True:
        async with get_task_db_session() as db:
            rows = await repo.get_idle_conversations_batch(
                db,
                idle_before=idle_before,
                after_id=last_id,
                limit=CHAT_IDLE_BATCH_SIZE,
            )

        if not rows:
            break

        batch_count += 1
        logger.debug("[idle-cron] processing batch=%d rows=%d after_id=%d", batch_count, len(rows), last_id)

        for row in rows:
            try:
                chat_completion_task.apply_async(
                    kwargs={
                        "conversation__id": row.id,
                        "tenant_id": row.tenant_id,
                    },
                    queue=QUEUEEnum.ANALYSIS.value,
                )
                total_spawned += 1
                logger.debug("[idle-cron] spawned task for conversation_id=%s tenant=%s", row.id, row.tenant_id)
            except Exception as exc:
                logger.error(
                    "[idle-cron] failed to spawn for conversation_id=%s error=%s",
                    row.id, exc, exc_info=True,
                )

        last_id = rows[-1].id

        if len(rows) < CHAT_IDLE_BATCH_SIZE:
            break

    logger.info("[idle-cron] _dispatch_in_batches done total_spawned=%d batches=%d", total_spawned, batch_count)
    return total_spawned
