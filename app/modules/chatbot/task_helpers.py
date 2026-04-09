"""
app/modules/knowledge/task_helpers.py

Pure sync/async helpers called by Celery tasks.
No Celery imports here — keeps logic testable outside of a worker.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Chunk settings ────────────────────────────────────────────────────────────
CHUNK_SIZE = 500  # tokens (approximate — we use word count as proxy)
CHUNK_OVERLAP = 50  # words of overlap between consecutive chunks


# =============================================================================
# TEXT CHUNKING
# =============================================================================


def chunk_text(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> List[str]:
    """
    Split text into overlapping word-based chunks.
    Simple and deterministic — swap for tiktoken later if you need exact tokens.

    Returns:
        List of chunk strings, each ≤ chunk_size words.
    """
    if not text or not text.strip():
        return []

    words = text.split()
    if not words:
        return []

    chunks: List[str] = []
    start = 0

    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        if end >= len(words):
            break
        start += chunk_size - overlap  # slide window with overlap

    return chunks


def chunk_pages(
    pages: List[Dict[str, Any]],
    source_url: Optional[str] = None,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> List[Dict[str, Any]]:
    """
    Chunk a list of parsed PDF/HTML pages into individual chunk dicts.

    Args:
        pages:      List of {page_number, text, tables} dicts from parser.
        source_url: Origin URL (for crawled pages).
        chunk_size: Max words per chunk.
        overlap:    Word overlap between consecutive chunks.

    Returns:
        List of dicts ready to become DocumentChunk rows:
        {
            "chunk_index": int,
            "content": str,
            "metadata": {"page": int, "source_url": str, "token_count": int}
        }
    """
    result: List[Dict[str, Any]] = []
    global_index = 0

    for page in pages:
        page_num = page.get("page_number", 0)
        text = page.get("text", "")

        # Include table data as plain text after the page text
        tables = page.get("tables", [])
        table_text = _tables_to_text(tables)
        full_text = f"{text}\n\n{table_text}".strip() if table_text else text

        chunks = chunk_text(full_text, chunk_size=chunk_size, overlap=overlap)

        for chunk in chunks:
            word_count = len(chunk.split())
            metadata: Dict[str, Any] = {
                "page": page_num,
                "token_count": word_count,
            }
            if source_url:
                metadata["source_url"] = source_url

            result.append(
                {
                    "chunk_index": global_index,
                    "content": chunk,
                    "metadata": metadata,
                }
            )
            global_index += 1

    return result



def chunk_plain_text(
    text: str,
    source_url: Optional[str] = None,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> List[Dict[str, Any]]:
    """
    Chunk a single block of plain text (crawled HTML page, manual text, etc.).
    """
    chunks = chunk_text(text, chunk_size=chunk_size, overlap=overlap)
    result = []
    for idx, chunk in enumerate(chunks):
        metadata: Dict[str, Any] = {"token_count": len(chunk.split())}
        if source_url:
            metadata["source_url"] = source_url
        result.append(
            {
                "chunk_index": idx,
                "content": chunk,
                "metadata": metadata,
            }
        )
    return result


# =============================================================================
# TABLE HELPER
# =============================================================================


def _tables_to_text(tables: List[List[List[str]]]) -> str:
    """
    Convert pdfplumber table arrays into readable plain text rows.
    [[["Col A", "Col B"], ["Val 1", "Val 2"]]] →
    "Col A | Col B\nVal 1 | Val 2"
    """
    lines: List[str] = []
    for table in tables:
        for row in table:
            lines.append(" | ".join(str(cell) for cell in row))
        lines.append("")  # blank line between tables
    return "\n".join(lines).strip()


# =============================================================================
# EMBEDDING BATCH HELPER
# =============================================================================


async def embed_chunks(
    chunks: List[Dict[str, Any]],
    openai_service: Any,
    batch_size: int = 100,
) -> List[Dict[str, Any]]:
    """
    Add 'embedding' key to each chunk dict.
    Batches calls to stay within OpenAI rate limits.

    Args:
        chunks:         List from chunk_pages() / chunk_plain_text().
        openai_service: Module with embed_texts(texts: List[str]) → List[List[float]].
        batch_size:     Texts per API call (OpenAI max is 2048 inputs).

    Returns:
        Same list with 'embedding' added to each dict.
    """
    texts = [c["content"] for c in chunks]
    embeddings: List[List[float]] = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        batch_embeddings = await openai_service.embed_texts(batch)
        embeddings.extend(batch_embeddings)
        logger.debug(f"Embedded batch {i}–{i + len(batch)} ({len(batch)} chunks)")

    for chunk, embedding in zip(chunks, embeddings):
        chunk["embedding"] = embedding

    return chunks


# =============================================================================
# CONTENT CLEANING
# =============================================================================


def build_listing_embed_text(listing: Any) -> str:
    """
    Build a single string that captures all queryable listing attributes.
    Embedded as a single vector on the listings table for semantic fallback.

    Format keeps it human-readable so the model can use it well:
    "For sale | 3 bed | 2 bath | Paddington NSW | $1.2M–$1.4M | ..."
    """
    parts: List[str] = []

    # Type + status
    if hasattr(listing, "listing_type") and listing.listing_type:
        parts.append(str(listing.listing_type.value).replace("_", " "))
    if hasattr(listing, "status") and listing.status:
        parts.append(str(listing.status.value).replace("_", " "))

    # Bedrooms / bathrooms / garages
    features: List[str] = []
    if listing.bedrooms:
        features.append(f"{listing.bedrooms} bed")
    if listing.bathrooms:
        features.append(f"{listing.bathrooms} bath")
    if listing.garages:
        features.append(f"{listing.garages} garage")
    if listing.has_pool:
        features.append("pool")
    if features:
        parts.append(" / ".join(features))

    # Location
    location: List[str] = []
    if listing.suburb:
        location.append(listing.suburb)
    if listing.state:
        location.append(listing.state)
    if listing.postcode:
        location.append(listing.postcode)
    if location:
        parts.append(", ".join(location))

    # Price
    if listing.price_display:
        parts.append(listing.price_display)
    elif listing.price:
        parts.append(f"{listing.currency} {listing.price:,.0f}")

    # Title and description (capped to avoid token bloat)
    if listing.title:
        parts.append(listing.title)
    if listing.description:
        parts.append(listing.description[:600])

    return " | ".join(p for p in parts if p)


def clean_html_text(raw: str) -> str:
    """
    Remove excess whitespace and noise lines from scraped HTML text.
    Shared between website_parser and task_helpers.
    """
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in raw.splitlines()]
    return "\n".join(
        line for line in lines if line and not re.fullmatch(r"[\-\–\—\d\s]+", line)
    )
