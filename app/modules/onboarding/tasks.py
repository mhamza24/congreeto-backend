import json
import time
import asyncio
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from app.config.celery_worker import celery_app, QUEUEEnum
from app.modules.onboarding.parsers import website_parser
import logging
logger = logging.getLogger(__name__)
from app.config.settings import get_settings
settings = get_settings()

class TaskError(Exception):
    pass


@celery_app.task
def background_analysis(conversation_id: str):
    print(f"Analyzing conversation {conversation_id}")


@celery_app.task(
    bind=True,
    name="app.modules.onboarding.tasks.live_link_scrapper",
    max_retries=settings.CELERY_MAX_TRIES,
    default_retry_delay=settings.CELERY_DEFAULT_RETRY_DELAY,
    queue=QUEUEEnum.INGESTION.value,
)
def live_link_scrapper(self, link: str) -> str:
    if not link:
        raise ValueError("No link provided")

    try:
        # Safely run async code in sync Celery task
        result = asyncio.run(website_parser.scrape_websites(link))
        print(result)
        # Save result to DB here if needed
        logger.info(f"Scraping completed for link: {link}")
        print(f"Scraping completed for link: {link}")

        return "Scraping completed successfully"

    except Exception as exc:
        countdown = 2 ** self.request.retries
        logger.error(f"Error scraping {link}, retrying in {countdown}s: {exc}")
        raise self.retry(exc=exc, countdown=countdown)