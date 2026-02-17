import logging
from app.config.settings import get_settings, Settings


def setup_logging():
    # settings = get_settings()
    settings = Settings()

    log_format = (
        "%(asctime)s | %(levelname)s | %(name)s | "
        "%(filename)s:%(lineno)d | %(message)s"
    )

    logging.basicConfig(
        level=settings.LOG_LEVEL,
        format=log_format,
    )

    logger = logging.getLogger()
    logger.info(f"Logging initialized in {settings.ENV} mode")
