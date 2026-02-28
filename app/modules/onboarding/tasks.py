import json
import time
import asyncio
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from app.config.celery_worker import celery_app
from app.modules.onboarding.parsers import website_parser
from app.config.settings import get_settings
settings = get_settings()

class TaskError(Exception):
    pass



@celery_app.task(
    bind=True,
    name="app.modules.onboarding.tasks.scrape_website",
    max_retries=settings.CELERY_MAX_TRIES,
    default_retry_delay=settings.CELERY_DEFAULT_RETRY_DELAY,
)
def live_link_scrapper(self, link: str) -> str:

    if not link:
        raise ValueError("No link provided")

    try:
        result = asyncio.run(
            website_parser.scrape_websites(link)
        )

        # Save result to DB here

        return "Scraping completed successfully"

    except Exception as exc:
        countdown = 2 ** self.request.retries
        raise self.retry(exc=exc, countdown=countdown)