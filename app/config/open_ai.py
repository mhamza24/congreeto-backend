from openai import AsyncOpenAI
from app.config.settings import get_settings

settings = get_settings()

# Initialize the ASYNC client
async_client = AsyncOpenAI(
    api_key=settings.OPEN_AI_KEY,

)
# timeout=30.0,
# max_retries=3,
OPENAI_API_KEY = settings.OPEN_AI_KEY
OPENAI_MODEL = settings.OPEN_AI_MODEL
OPENAI_MAX_TOKENS = settings.OPEN_AI_MAX_TOKENS
OPENAI_TEMPERATURE = settings.OPEN_AI_TEMPERATURE
