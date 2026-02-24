import json
import time
import asyncio
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from app.config.celery_worker import celery_app


class TaskError(Exception):
    pass



@celery_app.task(
    bind=True,
    name="app.modules.onboarding.tasks.scrape_website",
    max_retries=3,
    default_retry_delay=5,  # seconds
)
def live_link_scrapper(self, link: str) -> str:
    """
    Celery task to scrape a live website.
    """

    try:
        if not link:
            raise TaskError("No link provided")

        # Replace with real scraping logic
        print(f"[Task ID: {self.request.id}] Scraping link: {link}")

        # Simulate processing
        # real scraping logic goes here

        return "Scraping completed successfully"

    except Exception as exc:
        # Retry with exponential backoff
        countdown = 2 ** self.request.retries
        raise self.retry(exc=exc, countdown=countdown)