import asyncio
import logging
import re
from typing import List

from app.utils.llm_response_cleaner import clean_response_helper
from app.config.open_ai import async_client, OPENAI_MODEL, OPENAI_MAX_TOKENS, OPENAI_TEMPERATURE, OPEN_AI_FREQUENCY_PENALTY, OPEN_AI_PRESENCE_PENALTY, OPEN_AI_TOP_P

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "text-embedding-3-small"  # 1536-dim, matches Vector(1536) in models

# Max concurrent embedding requests — keeps us well inside OpenAI's RPM limit
_EMBED_SEMAPHORE = asyncio.Semaphore(5)


async def embed_text(text: str) -> List[float]:
    """Embed a single string. Used by rag_search for query embedding."""
    response = await async_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text,
    )
    return response.data[0].embedding


async def embed_texts(texts: List[str]) -> tuple[List[List[float]], int]:
    """Batch embed multiple strings, auto-split to stay under OpenAI's
    300 000-token-per-request limit and sent concurrently (up to 5 in-flight).
    Returned list preserves input order.

    Returns:
        (embeddings, num_api_calls) — callers can log the actual batch count.
    """
    if not texts:
        return []

    # ~4 chars per token; 250 000-token budget leaves a comfortable safety margin
    MAX_CHARS_PER_BATCH = 250_000 * 4

    # ── Build batches ────────────────────────────────────────────────────────
    batches: list[list[str]] = []
    current_batch: list[str] = []
    current_chars = 0

    for text in texts:
        text_chars = len(text)
        if current_batch and current_chars + text_chars > MAX_CHARS_PER_BATCH:
            batches.append(current_batch)
            current_batch = []
            current_chars = 0
        current_batch.append(text)
        current_chars += text_chars

    if current_batch:
        batches.append(current_batch)

    total = len(batches)
    logger.debug("embed_texts: %d texts → %d batches (concurrent, sem=5)", len(texts), total)

    # ── Fire all batches concurrently, capped by semaphore ───────────────────
    async def _embed_batch(idx: int, batch: list[str]) -> tuple[int, list[list[float]]]:
        async with _EMBED_SEMAPHORE:
            logger.debug("embed_texts: batch %d/%d (%d texts) — start", idx + 1, total, len(batch))
            response = await async_client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=batch,
            )
            logger.debug("embed_texts: batch %d/%d — done", idx + 1, total)
            embeddings = [
                item.embedding
                for item in sorted(response.data, key=lambda x: x.index)
            ]
            return idx, embeddings

    results: list[tuple[int, list[list[float]]]] = await asyncio.gather(
        *(_embed_batch(i, b) for i, b in enumerate(batches))
    )

    # Reassemble in original order
    ordered = sorted(results, key=lambda r: r[0])
    all_embeddings: list[list[float]] = []
    for _, batch_embeddings in ordered:
        all_embeddings.extend(batch_embeddings)

    return all_embeddings, total
 
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


async def openai_call_json(
    messages: list,
    system_instructions: str,
    max_tokens: int = 1500,
) -> str:
    """
    Call the LLM with strict JSON output enforced via response_format.

    Use this whenever the caller expects to json.loads() the response.
    The API guarantees syntactically valid JSON — no markdown fences, no prose.

    NOTE: The system_instructions or message content MUST contain the word
    'JSON' (OpenAI requirement for json_object mode).

    Returns the raw JSON string. Raises on API error so callers can handle
    the fallback themselves.
    """
    params = {**OPENAI_CALL_PARAMS, "max_tokens": max_tokens}
    response = await async_client.chat.completions.create(
        messages=[
            {"role": "system", "content": system_instructions},
            *messages,
        ],
        response_format={"type": "json_object"},
        **params,
    )
    return response.choices[0].message.content or "{}"


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
