from sqlalchemy.ext.asyncio import AsyncSession
import asyncio
import json

from celery.schedules import crontab
from sqlalchemy import text
from app.utils.system_prompt_chat_analysis import system_prompt_extract_chat_insights
from app.config.settings import get_settings
from app.core.database import get_task_db_session
from app.config.celery_worker import celery_app, QUEUEEnum
from app.modules.open_ai import service as ai_service
import logging
from . import repository as repo
from .task_helper import (
    send_otp_verification_email_helper,
    send_login_otp_email_helper,
    send_forgot_password_email_helper,
)


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
    logger.info("[auth] send_otp_verification_email_task started email=%s attempt=%d", email, self.request.retries + 1)
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                send_otp_verification_email_helper(email=email, first_name=first_name, otp_code=otp_code))
        finally:
            loop.close()
            asyncio.set_event_loop(None)

        logger.info("[auth] send_otp_verification_email_task succeeded email=%s", email)
        return {"email": email, "result": result}
    except Exception as exc:
        countdown = min(300, 2 ** self.request.retries * 10)
        logger.warning("[auth] send_otp_verification_email_task failed email=%s retry_in=%ds error=%s", email, countdown, exc)
        raise self.retry(exc=exc, countdown=countdown)


@celery_app.task(
    bind=True,
    name="app.modules.auth.tasks.send_login_otp_email_task",
    max_retries=settings.CELERY_MAX_TRIES,
    default_retry_delay=settings.CELERY_DEFAULT_RETRY_DELAY,
    queue=QUEUEEnum.ANALYSIS.value,
)
def send_login_otp_email_task(self, email: str, first_name: str, otp_code: str):
    logger.info("[auth] send_login_otp_email_task started email=%s attempt=%d", email, self.request.retries + 1)
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                send_login_otp_email_helper(email=email, first_name=first_name, otp_code=otp_code))
        finally:
            loop.close()
            asyncio.set_event_loop(None)
        logger.info("[auth] send_login_otp_email_task succeeded email=%s", email)
        return {"email": email, "result": result}
    except Exception as exc:
        countdown = min(300, 2 ** self.request.retries * 10)
        logger.warning("[auth] send_login_otp_email_task failed email=%s retry_in=%ds error=%s", email, countdown, exc)
        raise self.retry(exc=exc, countdown=countdown)


@celery_app.task(
    bind=True,
    name="app.modules.auth.tasks.send_forgot_password_email_task",
    max_retries=settings.CELERY_MAX_TRIES,
    default_retry_delay=settings.CELERY_DEFAULT_RETRY_DELAY,
    queue=QUEUEEnum.ANALYSIS.value,
)
def send_forgot_password_email_task(self, email: str, first_name: str, otp_code: str, reset_link: str):
    logger.info("[auth] send_forgot_password_email_task started email=%s attempt=%d", email, self.request.retries + 1)
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                send_forgot_password_email_helper(
                    email=email, first_name=first_name, otp_code=otp_code, reset_link=reset_link
                ))
        finally:
            loop.close()
            asyncio.set_event_loop(None)
        logger.info("[auth] send_forgot_password_email_task succeeded email=%s", email)
        return {"email": email, "result": result}
    except Exception as exc:
        countdown = min(300, 2 ** self.request.retries * 10)
        logger.warning("[auth] send_forgot_password_email_task failed email=%s retry_in=%ds error=%s", email, countdown, exc)
        raise self.retry(exc=exc, countdown=countdown)


@celery_app.task(
    name="app.modules.auth.tasks.cleanup_expired_otps",
    queue=QUEUEEnum.ANALYSIS.value,
)
def cleanup_expired_otps():
    """
    Deletes OTP records that expired more than 24 hours ago.
    Runs nightly via Celery Beat to keep the otp_verifications table lean.
    """
    async def _run():
        async with get_task_db_session() as db:
            result = await db.execute(
                text(
                    "DELETE FROM otp_verifications "
                    "WHERE expires_at < NOW() - INTERVAL '24 hours'"
                )
            )
            await db.commit()
            return result.rowcount

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        deleted = loop.run_until_complete(_run())
        logger.info("[auth] cleanup_expired_otps deleted=%d rows", deleted)
        return {"deleted": deleted}
    except Exception as exc:
        logger.error("[auth] cleanup_expired_otps failed error=%s", exc)
        raise
    finally:
        loop.close()
        asyncio.set_event_loop(None)
