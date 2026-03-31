import logging
from app.modules.email import service as email_service
from app.config.settings import get_settings
settings = get_settings()
logger = logging.getLogger(__name__)


async def send_otp_verification_email_helper(
    *,
    email     : str,
    first_name: str,
    otp_code  : str,
) -> None:
    """
    Triggered on signup.
    Sends a single email combining welcome + OTP verification.

    Called via Celery:
        send_otp_verification_task.delay(
            email      = user.email,
            first_name = user.first_name,
            otp_code   = raw_otp,
        )
    """
    try:
        email_service.send_otp_verification_email(email=email,first_name=first_name,otp_code=otp_code)
        logger.info(f"OTP verification email sent | recipient={email}")

    except Exception:
        logger.exception(f"Failed to send OTP verification email | recipient={email}")
        raise