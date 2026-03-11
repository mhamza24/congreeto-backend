import logging
import re

from app.config.open_ai import async_client, OPENAI_MODEL, OPENAI_MAX_TOKENS, OPENAI_TEMPERATURE, OPEN_AI_FREQUENCY_PENALTY, OPEN_AI_PRESENCE_PENALTY, OPEN_AI_TOP_P
logger = logging.getLogger(__name__)

# Define common OpenAI call parameters once
OPENAI_CALL_PARAMS = {
    "model": OPENAI_MODEL,
    "max_tokens": OPENAI_MAX_TOKENS,
    "temperature": OPENAI_TEMPERATURE,
    "top_p": OPEN_AI_TOP_P,
    "frequency_penalty": OPEN_AI_FREQUENCY_PENALTY,
    "presence_penalty": OPEN_AI_PRESENCE_PENALTY,
}

async def openai_call_conversation(messages: list, system_instructions: str) -> str:
    try:
        response = await async_client.chat.completions.create(
            messages=[
                {"role": "system", "content":
                    system_instructions},
                *messages,  # spread the full history including current user message
            ],
            **OPENAI_CALL_PARAMS
        )
        cleaned_response = re.sub(
            r"[—–-]", ",", response.choices[0].message.content)
        return cleaned_response
    except Exception as e:
        logger.error(f"OpenAI API error: {e}")
        return "Sorry, I could not generate a response. Please try again shortly."



async def openai_call_conversation_analysis(messages: list, system_instructions: str) -> str:
    try:
        response = await async_client.chat.completions.create(
            messages=[
                {"role": "system", "content":
                    system_instructions},
                *messages,  # spread the full history including current user message
            ],
            **OPENAI_CALL_PARAMS
        )
        cleaned_response = re.sub(
            r"[—–-]", ",", response.choices[0].message.content)
        return cleaned_response

    except Exception as e:
        logger.error(f"OpenAI API error: {e}")
        return "Sorry, I could not generate a response. Please try again shortly."
