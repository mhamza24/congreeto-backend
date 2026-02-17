from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    ENV: str
    DEBUG: bool = False

    DATABASE_URL: str
    REDIS_URL: str

    JWT_SECRET: str
    JWT_ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int

    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = ".env.development"


@lru_cache
def get_settings():
    return Settings()
