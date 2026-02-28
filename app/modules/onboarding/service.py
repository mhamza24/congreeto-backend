from __future__ import annotations

import json
import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.open_ai import service as openai_service
from app.utils.system_prompt_aria import aria_veloce_website_guide
from app.utils.system_prompt_aria_veloce import aria_veloce_brand_representative
from app.modules.onboarding import tasks as background_tasks
from . import repository as repo
from . import schemas

logger = logging.getLogger(__name__)


async def scrap_website_data(
    db: AsyncSession,
    *,
    payload: schemas.liveLinkScrapperRequest,
) -> schemas.liveLinkScrapperResponse:

    celery_task = background_tasks.live_link_scrapper.delay(payload.link)

    logger.info(
        f"Task enqueued: {celery_task.id}, initial status: {celery_task.status}")
    print(
        f"Task enqueued: {celery_task.id}, initial status: {celery_task.status}")

    return schemas.liveLinkScrapperResponse(
        id=celery_task.id,
        status=celery_task.status

    )
