import logging
from contextvars import ContextVar

from app.config.settings import get_settings


# ─────────────────────────────────────────────────────────────────────────────
# Request-scoped context
# ─────────────────────────────────────────────────────────────────────────────
# request_id is set by RequestLoggingMiddleware at the start of every HTTP
# request and consumed by the LogRecordFactory below so every log line emitted
# inside the request handler carries the same correlation id.
#
# ContextVar is async-safe (each Task gets its own value) and lookup is O(1)
# — overhead per log line is well under a microsecond.
# ─────────────────────────────────────────────────────────────────────────────
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def _install_request_id_factory() -> None:
    """
    Hook a custom LogRecordFactory that copies the current request_id
    onto every LogRecord so it can be referenced via %(request_id)s in
    the logging format string.
    """
    base_factory = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        record = base_factory(*args, **kwargs)
        record.request_id = request_id_var.get()
        return record

    logging.setLogRecordFactory(factory)


def setup_logging():
    settings = get_settings()

    log_format = (
        "%(asctime)s | %(levelname)s | %(request_id)s | %(name)s | "
        "%(filename)s:%(lineno)d | %(message)s"
    )

    logging.basicConfig(
        level=settings.LOG_LEVEL,
        format=log_format,
    )

    _install_request_id_factory()

    # Tame noisy third-party loggers in production so the request log stays readable.
    if settings.ENV.upper() == "PRODUCTION":
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
        logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    logger = logging.getLogger()
    logger.info(f"Logging initialized in {settings.ENV} mode")
