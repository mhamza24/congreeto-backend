import logging
from app.config.open_ai import async_client, OPENAI_MODEL, OPENAI_MAX_TOKENS, OPENAI_TEMPERATURE

logger = logging.getLogger(__name__)


async def call_openai(messages: list, system_instructions: str = "You are a helpful assistant.") -> str:
    try:
        print("messages", messages)
        print("system_instructions", system_instructions)
        response = await async_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_instructions},
                *messages,  # spread the full history including current user message
            ],
            max_tokens=OPENAI_MAX_TOKENS,
            temperature=OPENAI_TEMPERATURE,
        )
        print("response:::", response)
        print("answer::::::::", response.choices[0].message.content)
        return response.choices[0].message.content

    except Exception as e:
        logger.error(f"OpenAI API error: {e}")
        return "Sorry, I could not generate a response. Please try again shortly."
