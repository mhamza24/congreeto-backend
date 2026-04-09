import logging
from app.modules.email import service as email_service

logger = logging.getLogger(__name__)


async def send_invite_email_helper(
    *,
    to: str,
    first_name: str,
    inviter_name: str,
    tenant_name: str,
    invite_link: str,
    role: str,
) -> None:
    """
    Sends the tenant invite email.

    Called via Celery:
        send_invite_email_task.delay(
            to           = payload.email,
            first_name   = first_name,
            inviter_name = current_user.full_name,
            tenant_name  = tenant.name,
            invite_link  = invite_link,
            role         = payload.role.value,
        )
    """
    try:
        await email_service.send_invite_email(
            to           = to,
            first_name   = first_name,
            inviter_name = inviter_name,
            tenant_name  = tenant_name,
            invite_link  = invite_link,
            role         = role,
        )
        logger.info(f"Invite email sent | recipient={to}")
    except Exception:
        logger.exception(f"Failed to send invite email | recipient={to}")
        raise
