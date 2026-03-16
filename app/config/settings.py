import os
from functools import lru_cache
from pydantic_settings import BaseSettings


ENV = os.getenv("ENV", "DEVELOPMENT")

ENV_FILES = {
    "DEVELOPMENT": ".env.development",
    "STAGING": ".env.staging",
    "PRODUCTION": ".env",
}


class Settings(BaseSettings):
    APP_NAME: str = "Veloce Backend"

    ENV: str
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    ALEMBIC_DATABASE_URL: str
    DATABASE_URL: str
    REDIS_URL: str

    JWT_SECRET: str
    JWT_ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int

    IDENTITY_HASH_SALT: str

    CELERY_RESULT_EXPIRES: int = 18000
    CELERY_TASK_TRACK_STARTED: bool = True
    CELERY_TASK_SERIALIZER: str = "json"
    CELERY_USE_SSL: bool = False
    CELERY_DEFAULT_QUEUE: str = "default"
    CELERY_MAX_TRIES: int = 3
    CELERY_DEFAULT_RETRY_DELAY: int = 5

    OPEN_AI_KEY: str
    OPEN_AI_MODEL: str = "gpt-4.1"
    OPEN_AI_MAX_TOKENS: int = 800
    OPEN_AI_MAX_RETRIES: int = 3
    OPEN_AI_TIMEOUT: float = 30.0
    OPEN_AI_TEMPERATURE: float = 0.48
    OPEN_AI_TOP_P: float = 0.9
    OPEN_AI_FREQUENCY_PENALTY: float = 0.1
    OPEN_AI_PRESENCE_PENALTY: float = 0.1

    SCRAPPER_WEB_MAX_PAGES: int = 100
    SCRAPPER_WEB_HEADLESS: bool = True
    SCRAPPER_WEB_TIMEOUT: int = 30_000
    SCRAPPER_PDF_TIMEOUT: int = 30

    MAIL_USERNAME: str
    MAIL_PASSWORD: str
    MAIL_FROM: str
    MAIL_SERVER: str = "smtp.office365.com"
    MAIL_PORT: int = 587

    SENTRY_DSN: str

    CHAT_IDLE_THRESHOLD_MINUTES: int = 15
    CHAT_IDLE_BATCH_SIZE: int = 100
    CHAT_PREVIOUS_CONVERSATION_SESSION_LIMIT: int = 5
    
    
    class Config:
        env_file = ENV_FILES.get(ENV, ".env.development")




@lru_cache
def get_settings():
    return Settings()
