import asyncio
import logging

from app.config.celery_worker import celery_app, QUEUEEnum
from app.config.settings import get_settings
from .task_helper import send_invite_email_helper

logger = logging.getLogger(__name__)
settings = get_settings()


@celery_app.task(
    bind=True,
    name="app.modules.tenants.tasks.send_invite_email_task",
    max_retries=settings.CELERY_MAX_TRIES,
    default_retry_delay=settings.CELERY_DEFAULT_RETRY_DELAY,
    queue=QUEUEEnum.ANALYSIS.value,
)
def send_invite_email_task(
    self,
    to: str,
    first_name: str,
    inviter_name: str,
    tenant_name: str,
    invite_link: str,
    role: str,
):
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                send_invite_email_helper(
                    to           = to,
                    first_name   = first_name,
                    inviter_name = inviter_name,
                    tenant_name  = tenant_name,
                    invite_link  = invite_link,
                    role         = role,
                )
            )
        finally:
            loop.close()
            asyncio.set_event_loop(None)

        return {"to": to, "result": result}
    except Exception as exc:
        countdown = min(300, 2 ** self.request.retries * 10)
        raise self.retry(exc=exc, countdown=countdown)
