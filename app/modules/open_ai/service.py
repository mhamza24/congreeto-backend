import logging
from app.config.open_ai import async_client, OPENAI_MODEL, OPENAI_MAX_TOKENS, OPENAI_TEMPERATURE
logger = logging.getLogger(__name__)


async def openai_call_conversation(messages: list, system_instructions: str) -> str:
    try:
        response = await async_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content":
                    system_instructions},
                *messages,  # spread the full history including current user message
            ],
            max_tokens=OPENAI_MAX_TOKENS,
            temperature=OPENAI_TEMPERATURE,
        )
        return response.choices[0].message.content

    except Exception as e:
        logger.error(f"OpenAI API error: {e}")
        return "Sorry, I could not generate a response. Please try again shortly."



async def openai_call_conversation_analysis(messages: list, system_instructions: str) -> str:
    try:
        response = await async_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content":
                    system_instructions},
                *messages,  # spread the full history including current user message
            ],
            max_tokens=OPENAI_MAX_TOKENS,
            temperature=OPENAI_TEMPERATURE,
        )
        return response.choices[0].message.content

    except Exception as e:
        logger.error(f"OpenAI API error: {e}")
        return "Sorry, I could not generate a response. Please try again shortly."
