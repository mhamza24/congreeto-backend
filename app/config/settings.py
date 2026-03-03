from pydantic_settings import BaseSettings
from functools import lru_cache


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
    OPEN_AI_TEMPERATURE: float = 0.7 #0.48
    
    #SCRAPPING SETTINGS
    SCRAPPER_WEB_MAX_PAGES:int=100  # safety cap — change as needed
    SCRAPPER_WEB_HEADLESS:bool=True  # set False to watch the browser
    SCRAPPER_WEB_TIMEOUT:int=30_000 # ms per page 
    
    SCRAPPER_PDF_TIMEOUT: int = 30  # seconds

    MAIL_USERNAME: str
    MAIL_PASSWORD: str
    MAIL_FROM: str
    MAIL_SERVER: str = "smtp.gmail.com"
    MAIL_PORT: int = 587



    class Config:
        env_file = ".env.development"


@lru_cache
def get_settings():
    return Settings()
