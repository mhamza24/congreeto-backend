from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    APP_NAME: str = "Veloce Backend"

    ENV: str
    DEBUG: bool = False

    ALEMBIC_DATABASE_URL: str
    DATABASE_URL: str
    REDIS_URL: str

    JWT_SECRET: str
    JWT_ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int

    CELERY_RESULT_EXPIRES: int = 18000
    CELERY_TASK_TRACK_STARTED: bool = True
    CELERY_TASK_SERIALIZER: str = "json"
    CELERY_USE_SSL: bool = False
    CELERY_DEFAULT_QUEUE: str = "default"

    OPEN_AI_KEY: str
    OPEN_AI_MODEL: str = "gpt-4.1"
    OPEN_AI_MAX_TOKENS: int = 800
    OPEN_AI_TEMPERATURE: float = 0.7 #0.48

    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = ".env.development"


@lru_cache
def get_settings():
    return Settings()
