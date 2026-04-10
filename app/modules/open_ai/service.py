import logging
import re
from typing import List

from app.utils.llm_response_cleaner import clean_response_helper
from app.config.open_ai import async_client, OPENAI_MODEL, OPENAI_MAX_TOKENS, OPENAI_TEMPERATURE, OPEN_AI_FREQUENCY_PENALTY, OPEN_AI_PRESENCE_PENALTY, OPEN_AI_TOP_P

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "text-embedding-3-small"  # 1536-dim, matches Vector(1536) in models


async def embed_text(text: str) -> List[float]:
    """Embed a single string. Used by rag_search for query embedding."""
    response = await async_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text,
    )
    return response.data[0].embedding


async def embed_texts(texts: List[str]) -> List[List[float]]:
    """Batch embed multiple strings. Used by embed_chunks in task_helpers."""
    if not texts:
        return []
    response = await async_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts,
    )
    # API returns results in the same order as input
    return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]
 
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
    """Legacy wrapper — returns content string only. Use openai_call_with_usage for new code."""
    content, _ = await openai_call_with_usage(messages, system_instructions)
    return content


async def openai_call_with_usage(
    messages: list,
    system_instructions: str,
) -> tuple[str, int]:
    """
    Call the LLM and return (cleaned_content, total_tokens_used).

    total_tokens_used is the sum of prompt + completion tokens reported by the
    API. This value is used to update usage records for billing enforcement.
    Returns 0 for tokens if the API call fails.
    """
    try:
        response = await async_client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_instructions},
                *messages,
            ],
            **OPENAI_CALL_PARAMS,
        )
        cleaned_response = clean_response_helper(response.choices[0].message.content)
        tokens_used = response.usage.total_tokens if response.usage else 0
        return cleaned_response, tokens_used
    except Exception as e:
        logger.error(f"OpenAI API error: {e}")
        return "Sorry, I could not generate a response. Please try again shortly.", 0



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
       
        cleaned_response =  clean_response_helper(response.choices[0].message.content)
        return cleaned_response

    except Exception as e:
        logger.error(f"OpenAI API error: {e}")
        return "Sorry, I could not generate a response. Please try again shortly."
