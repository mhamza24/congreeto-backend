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


# =============================================================================
# LISTING EXTRACTION FROM CRAWLED PAGE TEXT
# =============================================================================

_LISTING_EXTRACT_PROMPT = """\
You are a data extraction assistant for a real-estate platform.

Given the text scraped from a property listing webpage, extract all property listings you can find.
Return a JSON array. Each element must have these fields (use null when unknown):
{
  "title": "string — property title or address",
  "listing_type": "sale | rent",
  "status": "active | sold | leased",
  "description": "string or null",
  "price": float or null,
  "price_display": "string like $1,200,000 or $450/week or null",
  "currency": "AUD",
  "street": "string or null",
  "suburb": "string or null",
  "state": "string or null",
  "postcode": "string or null",
  "bedrooms": integer or null,
  "bathrooms": integer or null,
  "garages": integer or null,
  "land_sqm": float or null,
  "house_sqm": float or null,
  "has_pool": true | false
}

If the page contains NO property listings, return an empty array: []
Return ONLY the JSON array, no explanation.

PAGE TEXT:
"""


async def extract_listings_from_page(
    page_text: str,
    openai_service: Any,
    source_url: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Ask the LLM to extract structured listing data from a scraped page.
    Returns a (possibly empty) list of listing dicts.
    Failures are caught and logged — never raise, just return [].
    """
    import json

    # Don't waste tokens on very short pages
    if len(page_text.strip()) < 100:
        return []

    # Truncate to avoid hitting context limits (~12k chars ≈ 3k tokens)
    truncated = page_text[:12000]
    prompt = _LISTING_EXTRACT_PROMPT + truncated

    try:
        raw = await openai_service.openai_call_conversation(
            messages=[{"role": "user", "content": prompt}],
            system_instructions="You extract structured property listing data from webpage text. Return only valid JSON.",
        )
        # Strip markdown code fences if present
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        listings = json.loads(raw)
        if not isinstance(listings, list):
            return []

        # Attach source_url for traceability
        for item in listings:
            if source_url:
                item.setdefault("raw_data", {})["source_url"] = source_url

        logger.info(f"Listing extraction: found {len(listings)} listings from {source_url or 'page'}")
        return listings

    except Exception as exc:
        logger.warning(f"Listing extraction failed for {source_url}: {exc}")
        return []


def clean_html_text(raw: str) -> str:
    """
    Remove excess whitespace and noise lines from scraped HTML text.
    Shared between website_parser and task_helpers.
    """
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in raw.splitlines()]
    return "\n".join(
        line for line in lines if line and not re.fullmatch(r"[\-\–\—\d\s]+", line)
    )


# =============================================================================
# LLM PARSING FOR UPLOADED LISTING FILES (Excel / CSV)
# =============================================================================

_LISTING_FILE_PARSE_PROMPT = """\
You are a real-estate data cleaning and extraction assistant.

Below is tabular data from an uploaded property listing file (Excel or CSV).
Each row is one property listing. The first line is column headers; the rest are data rows separated by tabs.

The table contains exactly {row_count} data row(s). Return exactly {row_count} element(s) in the same order.

== YOUR TASKS ==

1. EXTRACT: Map each row to the output schema below.

2. CLEAN text fields:
   - Remove noise characters: `***`, `!!!`, `@@`, `##`, `---`, excessive punctuation, trailing numbers used as row IDs.
   - Trim whitespace. Convert ALL CAPS titles to Title Case.
   - If a description is clearly placeholder text (e.g. "needs cleanup", "test data", "lorem ipsum", random symbols), set it to null.
   - If a title is placeholder/gibberish, set it to "Property Listing".

3. FIX geographic inconsistencies:
   - If suburb and state are contradictory (e.g. suburb=Melbourne but state=NSW), correct the state to match the suburb using your knowledge of Australian geography.
   - Known mappings: Sydney→NSW, Melbourne→VIC, Brisbane→QLD, Perth→WA, Adelaide→SA, Hobart→TAS, Darwin→NT, Canberra→ACT.
   - Apply the same logic for well-known suburbs (e.g. Surry Hills→NSW, St Kilda→VIC, Fortitude Valley→QLD).

4. FIX price vs listing_type inconsistency:
   - If price_display contains "per week" or "pw" or "/wk", listing_type must be "rent".
   - If price_display contains a large lump sum (e.g. "$500,000") without weekly mention, listing_type should be "sale".
   - Price should be the numeric value only. If price and price_display clearly contradict each other, trust price_display and derive price from it.
   - If price is suspiciously low for a sale (e.g. < 10,000) but looks like a weekly rent, correct listing_type to "rent".

5. NULL out obviously wrong values:
   - Postcodes that don't match Australian format (4 digits) → null.
   - Negative or zero bedrooms/bathrooms/garages/sqm → null.
   - Prices of 0 or negative → null.
   - States that are not valid Australian states/territories → null.

== OUTPUT SCHEMA ==

Return a JSON array. Each element:
{{
  "title": "string — cleaned property title",
  "listing_type": "sale | rent",
  "status": "active | sold | leased | inactive",
  "description": "cleaned string or null",
  "price": float or null,
  "price_display": "formatted string or null",
  "currency": "AUD",
  "street": "string or null",
  "suburb": "string or null",
  "state": "corrected 2–3 letter state code or null",
  "postcode": "4-digit string or null",
  "bedrooms": integer or null,
  "bathrooms": integer or null,
  "garages": integer or null,
  "land_sqm": float or null,
  "house_sqm": float or null,
  "has_pool": true | false
}}

Return ONLY the JSON array. No explanation, no markdown, no extra text.

TABLE DATA:
"""

# ~20 rows per LLM call keeps each request under ~3k tokens and well within
# context limits while still amortizing the per-request overhead.
_LLM_BATCH_SIZE = 20


async def parse_listings_from_table(
    rows: List[Dict[str, Any]],
    openai_service: Any,
    batch_size: int = _LLM_BATCH_SIZE,
) -> List[Dict[str, Any]]:
    """
    Use the LLM to normalize and structure raw rows parsed from a CSV/Excel file.

    Batching strategy:
    - Each LLM call receives `batch_size` rows (default 20).
    - All batches are fired concurrently with asyncio.gather so the total
      wall-clock time is ~1 LLM call instead of N sequential calls.
    - On failure for any batch, falls back to the raw parsed rows for that batch.
    """
    import asyncio
    import json

    if not rows:
        return []

    async def _call_llm(batch: List[Dict[str, Any]], batch_start: int) -> List[Dict[str, Any]]:
        headers = list(batch[0].keys())
        table_lines = ["\t".join(str(h) for h in headers)]
        for row in batch:
            table_lines.append("\t".join(str(row.get(h, "") or "") for h in headers))
        table_text = "\n".join(table_lines)

        prompt = _LISTING_FILE_PARSE_PROMPT.format(row_count=len(batch)) + table_text

        try:
            raw = await openai_service.openai_call_conversation(
                messages=[{"role": "user", "content": prompt}],
                system_instructions=(
                    "You extract structured property listing data from tabular data. "
                    "Return only valid JSON."
                ),
            )
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

            parsed = json.loads(raw)
            if isinstance(parsed, list):
                logger.info(
                    f"LLM parsed rows {batch_start}–{batch_start + len(batch)}: "
                    f"{len(parsed)} listings"
                )
                return parsed

            logger.warning(f"LLM returned non-list for rows {batch_start}, using raw")
            return batch

        except Exception as exc:
            logger.error(
                f"LLM parse error for rows {batch_start}–{batch_start + len(batch)}: {exc}. "
                "Falling back to raw rows."
            )
            return batch

    # Fire all batch calls concurrently
    batches = [
        (rows[i: i + batch_size], i)
        for i in range(0, len(rows), batch_size)
    ]
    batch_results = await asyncio.gather(*[_call_llm(b, start) for b, start in batches])

    # Flatten results preserving order
    return [item for batch in batch_results for item in batch]
