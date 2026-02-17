import logging
from app.config.open_ai import async_client, OPENAI_MODEL, OPENAI_MAX_TOKENS, OPENAI_TEMPERATURE

logger = logging.getLogger(__name__)


async def call_openai(prompt: str, system_instructions: str = "You are a helpful assistant.") -> str:
    try:
        response = await async_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_instructions},
                {"role": "user", "content": prompt},
            ],
            max_tokens=OPENAI_MAX_TOKENS,
            temperature=OPENAI_TEMPERATURE,
        )
        return response.choices[0].message.content

        # Parse the JSON directly from the raw response
        data = raw_response.parse()

        # Access the text from the parsed dictionary/object
        output_text = data.output_text
        return output_text

    except Exception as e:
        logger.error(f"OpenAI API error: {e}")
        return "Sorry, I could not generate a response."
