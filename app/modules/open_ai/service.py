import asyncio
import logging
import re
from typing import List

import openai

from app.config.settings import get_settings
from app.core.circuit_breaker import CircuitBreaker, CircuitOpenError
from app.utils.llm_response_cleaner import clean_response_helper
from app.config.open_ai import (
    async_client,
    OPENAI_MODEL,
    OPENAI_MAX_TOKENS,
    OPENAI_TEMPERATURE,
    OPEN_AI_FREQUENCY_PENALTY,
    OPEN_AI_PRESENCE_PENALTY,
    OPEN_AI_TOP_P,
)

logger = logging.getLogger(__name__)
_settings = get_settings()

# Embedding model — must match Vector(N) dim in models. Configurable so a
# future model swap (e.g. text-embedding-3-large → 3072 dim) is one env change.
EMBEDDING_MODEL = _settings.OPENAI_EMBEDDING_MODEL

# Max concurrent embedding requests — keeps us well inside OpenAI's RPM limit.
_EMBED_SEMAPHORE = asyncio.Semaphore(_settings.OPENAI_EMBED_CONCURRENCY)

# ── Circuit breaker ───────────────────────────────────────────────────────────
# Shared across all calls in this worker process (Redis-backed state is shared
# across all workers and Celery tasks).
# Only transient infrastructure errors trip the breaker; business errors
# (rate limits, bad requests, auth failures) are re-raised without counting.
_openai_cb = CircuitBreaker(
    name="openai",
    failure_threshold=_settings.OPENAI_CIRCUIT_FAILURE_THRESHOLD,
    recovery_timeout=_settings.OPENAI_CIRCUIT_RECOVERY_TIMEOUT,
    success_threshold=_settings.OPENAI_CIRCUIT_HALF_OPEN_SUCCESSES,
)

# Exceptions that count as circuit-breaker failures (transient infrastructure).
# RateLimitError is excluded: it should be handled with backoff, not a trip.
_TRANSIENT_ERRORS = (
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.InternalServerError,
)

# Define common OpenAI call parameters once.
OPENAI_CALL_PARAMS = {
    "model":             OPENAI_MODEL,
    "max_tokens":        OPENAI_MAX_TOKENS,
    "temperature":       OPENAI_TEMPERATURE,
    "top_p":             OPEN_AI_TOP_P,
    "frequency_penalty": OPEN_AI_FREQUENCY_PENALTY,
    "presence_penalty":  OPEN_AI_PRESENCE_PENALTY,
}

# ── Internal helpers — circuit-breaker-aware raw API calls ───────────────────

async def _cb_chat(messages: list, params: dict) -> object:
    """Call chat.completions.create through the circuit breaker."""
    try:
        return await _openai_cb.call(
            lambda: async_client.chat.completions.create(messages=messages, **params)
        )
    except _TRANSIENT_ERRORS:
        raise
    except CircuitOpenError:
        raise
    except openai.RateLimitError:
        # Rate limit: re-raise as-is; the caller decides how to handle.
        raise
    except openai.OpenAIError:
        # Other OpenAI errors (bad request, auth, etc.) — re-raise without tripping.
        raise


async def _cb_embed(model: str, input_data) -> object:
    """Call embeddings.create through the circuit breaker."""
    try:
        return await _openai_cb.call(
            lambda: async_client.embeddings.create(model=model, input=input_data)
        )
    except _TRANSIENT_ERRORS:
        raise
    except CircuitOpenError:
        raise
    except openai.OpenAIError:
        raise


# ── Public embedding functions ────────────────────────────────────────────────

async def embed_text(text: str) -> List[float]:
    """Embed a single string. Used by rag_search for query embedding."""
    response = await _cb_embed(EMBEDDING_MODEL, text)
    return response.data[0].embedding


async def embed_texts(texts: List[str]) -> tuple[List[List[float]], int]:
    """Batch embed multiple strings, auto-split to stay under OpenAI's
    300 000-token-per-request limit and sent concurrently (up to 5 in-flight).
    Returned list preserves input order.

    Returns:
        (embeddings, num_api_calls) — callers can log the actual batch count.
    """
    if not texts:
        return [], 0

    # ~4 chars per token; 250 000-token budget leaves a comfortable safety margin.
    MAX_CHARS_PER_BATCH = 250_000 * 4

    # ── Build batches ────────────────────────────────────────────────────────
    batches: list[list[str]] = []
    current_batch: list[str] = []
    current_chars = 0

    for t in texts:
        text_chars = len(t)
        if current_batch and current_chars + text_chars > MAX_CHARS_PER_BATCH:
            batches.append(current_batch)
            current_batch = []
            current_chars = 0
        current_batch.append(t)
        current_chars += text_chars

    if current_batch:
        batches.append(current_batch)

    total = len(batches)
    logger.debug("embed_texts: %d texts → %d batches (concurrent, sem=%d)",
                 len(texts), total, _settings.OPENAI_EMBED_CONCURRENCY)

    # ── Fire all batches concurrently, capped by semaphore ───────────────────
    async def _embed_batch(idx: int, batch: list[str]) -> tuple[int, list[list[float]]]:
        async with _EMBED_SEMAPHORE:
            logger.debug("embed_texts: batch %d/%d (%d texts) — start", idx + 1, total, len(batch))
            response = await _cb_embed(EMBEDDING_MODEL, batch)
            logger.debug("embed_texts: batch %d/%d — done", idx + 1, total)
            embeddings = [
                item.embedding
                for item in sorted(response.data, key=lambda x: x.index)
            ]
            return idx, embeddings

    results: list[tuple[int, list[list[float]]]] = await asyncio.gather(
        *(_embed_batch(i, b) for i, b in enumerate(batches))
    )

    ordered = sorted(results, key=lambda r: r[0])
    all_embeddings: list[list[float]] = []
    for _, batch_embeddings in ordered:
        all_embeddings.extend(batch_embeddings)

    return all_embeddings, total


# ── Public chat functions ─────────────────────────────────────────────────────

_CIRCUIT_OPEN_MSG = (
    "The AI service is temporarily unavailable. Please try again in a moment."
)
_API_ERROR_MSG = "Sorry, I could not generate a response. Please try again shortly."


async def openai_call_conversation(messages: list, system_instructions: str) -> str:
    """Legacy wrapper — returns content string only."""
    content, _ = await openai_call_with_usage(messages, system_instructions)
    return content


async def openai_call_with_usage(
    messages: list,
    system_instructions: str,
) -> tuple[str, int]:
    """
    Call the LLM and return (cleaned_content, total_tokens_used).

    Returns a fallback string and 0 tokens on any failure so callers remain
    non-blocking. The circuit breaker prevents hammering OpenAI when it's down.
    """
    try:
        full_messages = [{"role": "system", "content": system_instructions}, *messages]
        response = await _cb_chat(full_messages, OPENAI_CALL_PARAMS)
        cleaned = clean_response_helper(response.choices[0].message.content)
        tokens_used = response.usage.total_tokens if response.usage else 0
        return cleaned, tokens_used
    except CircuitOpenError:
        logger.warning("openai_call_with_usage: circuit open — returning fallback")
        return _CIRCUIT_OPEN_MSG, 0
    except Exception as e:
        logger.error("openai_call_with_usage error: %s", e)
        return _API_ERROR_MSG, 0


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
    full_messages = [{"role": "system", "content": system_instructions}, *messages]

    try:
        response = await _openai_cb.call(
            lambda: async_client.chat.completions.create(
                messages=full_messages,
                response_format={"type": "json_object"},
                **params,
            )
        )
        return response.choices[0].message.content or "{}"
    except CircuitOpenError:
        logger.warning("openai_call_json: circuit open — returning empty JSON")
        return "{}"
    # Let other errors propagate — callers handle their own fallback.


async def openai_call_conversation_analysis(
    messages: list,
    system_instructions: str,
) -> str:
    try:
        full_messages = [{"role": "system", "content": system_instructions}, *messages]
        response = await _cb_chat(full_messages, OPENAI_CALL_PARAMS)
        return clean_response_helper(response.choices[0].message.content)
    except CircuitOpenError:
        logger.warning("openai_call_conversation_analysis: circuit open — returning fallback")
        return _CIRCUIT_OPEN_MSG
    except Exception as e:
        logger.error("openai_call_conversation_analysis error: %s", e)
        return _API_ERROR_MSG
