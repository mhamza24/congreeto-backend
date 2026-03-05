import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from app.config.settings import get_settings

settings = get_settings()

def init_sentry():
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,

        # Environment identification
        environment=settings.ENV,   # dev / staging / production

        # Application version tracking
        release=settings.APP_NAME,

        # Performance monitoring
        traces_sample_rate=0.2,  # 20% of requests tracked

        # Error profiling
        profiles_sample_rate=0.1,

        # Attach stack traces to logs
        attach_stacktrace=True,

        # Send request/user info (be careful with privacy)
        send_default_pii=True,

        # Integrations
        integrations=[
            FastApiIntegration(),
            SqlalchemyIntegration(),
            LoggingIntegration(
                level=None,        # capture breadcrumbs
                event_level=None   # capture logs as events
            )
        ],

        # Capture request bodies for debugging
        max_request_body_size="medium",

        # Limit breadcrumb history
        max_breadcrumbs=50,

        # Ignore noisy errors
        ignore_errors=[
            "asyncio.CancelledError"
        ],

        # Enable debug mode in development
        debug=settings.DEBUG
    )
