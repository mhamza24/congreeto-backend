"""
app/modules/knowledge/task_helpers.py

Pure sync/async helpers called by Celery tasks.
No Celery imports here — keeps logic testable outside of a worker.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from app.config.settings import get_settings

_settings = get_settings()
logger = logging.getLogger(__name__)

# ── Chunk settings (sourced from settings.py — change there, not here) ────────
CHUNK_SIZE = _settings.CHUNK_SIZE
CHUNK_OVERLAP = _settings.CHUNK_OVERLAP


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
    batch_size: int = _settings.EMBED_BATCH_SIZE,
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
        batch_embeddings, _ = await openai_service.embed_texts(batch)
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
    Build a single human-readable string from a generic listing row.
    Works for any industry — reads from listing.attributes JSONB instead of
    industry-specific columns.

    Format: "real estate | active | bedrooms: 3 | bathrooms: 2 | Paddington, NSW | $1.2M | Title | Desc…"
    """
    parts: List[str] = []

    # Industry + status
    if getattr(listing, "industry", None):
        parts.append(str(listing.industry).replace("_", " "))
    status_val = getattr(listing, "status", None)
    if status_val:
        s = status_val.value if hasattr(status_val, "value") else str(status_val)
        parts.append(s.replace("_", " "))

    # Attributes (industry-specific fields — all treated uniformly)
    attrs: Dict[str, Any] = getattr(listing, "attributes", None) or {}
    attr_parts: List[str] = []
    for key, val in attrs.items():
        if val is None or val == "" or val is False:
            continue
        label = key.replace("_", " ")
        if isinstance(val, bool):
            attr_parts.append(label)
        elif isinstance(val, list):
            joined = ", ".join(str(v) for v in val if v)
            if joined:
                attr_parts.append(f"{label}: {joined}")
        else:
            attr_parts.append(f"{label}: {val}")
    if attr_parts:
        parts.extend(attr_parts)

    # Location (kept as first-class columns — useful for RE, restaurants, clinics)
    location: List[str] = []
    if getattr(listing, "suburb", None):
        location.append(listing.suburb)
    if getattr(listing, "state", None):
        location.append(listing.state)
    if getattr(listing, "postcode", None):
        location.append(listing.postcode)
    if location:
        parts.append(", ".join(location))

    # Price
    if getattr(listing, "price_display", None):
        parts.append(listing.price_display)
    elif getattr(listing, "price", None):
        currency = getattr(listing, "currency", "USD") or "USD"
        parts.append(f"{currency} {listing.price:,.0f}")

    # Title + description (capped to avoid token bloat)
    if getattr(listing, "title", None):
        parts.append(listing.title)
    if getattr(listing, "description", None):
        parts.append(listing.description[:600])

    return " | ".join(p for p in parts if p)


# =============================================================================
# DEFAULT INDUSTRY EXTRACTION PROMPTS
# Used as fallback when IndustrySchema.extraction_prompt is NULL.
# These are also the seed values written to the industry_schemas table by
# the Alembic migration — edit there (or update the DB row) to change them.
# =============================================================================

_DEFAULT_EXTRACTION_PROMPTS: Dict[str, str] = {
    "real_estate": """\
You are a data extraction assistant. Given text scraped from a real estate webpage, \
extract all property listings.

Return JSON: {"listings": [...]}. Each element:
{
  "title": "property title or address",
  "status": "active | sold | leased | inactive",
  "description": "string or null",
  "price": float or null,
  "price_display": "e.g. $1,200,000 or $450/week or null",
  "currency": "USD",
  "street": "string or null",
  "suburb": "string or null",
  "state": "string or null",
  "postcode": "string or null",
  "attributes": {
    "listing_type": "sale | rent",
    "bedrooms": integer or null,
    "bathrooms": integer or null,
    "garages": integer or null,
    "land_sqm": float or null,
    "house_sqm": float or null,
    "has_pool": true | false
  }
}
If NO listings found, return {"listings": []}.
PAGE TEXT:
""",
    "restaurant": """\
You are a data extraction assistant. Given text scraped from a restaurant or food website, \
extract all menu items.

Return JSON: {"listings": [...]}. Each element:
{
  "title": "item name",
  "status": "active | unavailable | seasonal",
  "description": "string or null",
  "price": float or null,
  "price_display": "e.g. $12.50 or null",
  "currency": "USD",
  "street": null, "suburb": null, "state": null, "postcode": null,
  "attributes": {
    "category": "e.g. Pizza, Burger, Dessert or null",
    "dietary_tags": ["vegan", "halal", "gluten-free"] or [],
    "spice_level": "mild | medium | hot | extra_hot or null",
    "preparation_time_minutes": integer or null
  }
}
If NO menu items found, return {"listings": []}.
PAGE TEXT:
""",
    "ecommerce": """\
You are a data extraction assistant. Given text scraped from an e-commerce webpage, \
extract all products.

Return JSON: {"listings": [...]}. Each element:
{
  "title": "product name",
  "status": "active | out_of_stock | discontinued",
  "description": "string or null",
  "price": float or null,
  "price_display": "e.g. $49.99 or null",
  "currency": "USD",
  "street": null, "suburb": null, "state": null, "postcode": null,
  "attributes": {
    "sku": "string or null",
    "brand": "string or null",
    "category": "string or null",
    "condition": "new | used | refurbished or null",
    "stock_quantity": integer or null,
    "weight_kg": float or null
  }
}
If NO products found, return {"listings": []}.
PAGE TEXT:
""",
    "cafe": """\
You are a data extraction assistant. Given text scraped from a cafe or coffee shop website, \
extract all menu items (coffees, food, drinks, specials, etc.).

Return JSON: {"listings": [...]}. Each element:
{
  "title": "item name",
  "status": "active | unavailable | seasonal",
  "description": "string or null",
  "price": float or null,
  "price_display": "e.g. $5.50 or null",
  "currency": "USD",
  "street": null, "suburb": null, "state": null, "postcode": null,
  "attributes": {
    "category": "e.g. Coffee, Tea, Food, Smoothie or null",
    "dietary_tags": ["vegan", "gluten-free", "dairy-free"] or [],
    "size_options": ["small", "medium", "large"] or [],
    "hot_or_cold": "hot | cold | both or null"
  }
}
If NO menu items found, return {"listings": []}.
PAGE TEXT:
""",
    "retail": """\
You are a data extraction assistant. Given text scraped from a retail store website, \
extract all products.

Return JSON: {"listings": [...]}. Each element:
{
  "title": "product name",
  "status": "active | out_of_stock | discontinued",
  "description": "string or null",
  "price": float or null,
  "price_display": "e.g. $29.99 or null",
  "currency": "USD",
  "street": null, "suburb": null, "state": null, "postcode": null,
  "attributes": {
    "brand": "string or null",
    "category": "string or null",
    "sizes_available": ["S", "M", "L"] or [],
    "colors_available": ["red", "blue"] or [],
    "in_stock": true | false
  }
}
If NO products found, return {"listings": []}.
PAGE TEXT:
""",
    "ux_template": """\
You are a data extraction assistant. Given text scraped from a UI/UX template marketplace, \
extract all templates.

Return JSON: {"listings": [...]}. Each element:
{
  "title": "template name",
  "status": "active | inactive",
  "description": "string or null",
  "price": float or null,
  "price_display": "e.g. $29 or Free or null",
  "currency": "USD",
  "street": null, "suburb": null, "state": null, "postcode": null,
  "attributes": {
    "tier": "free | premium",
    "framework": "e.g. React, Vue, Figma or null",
    "page_count": integer or null,
    "license_type": "personal | commercial | extended or null",
    "preview_url": "string or null",
    "category": "e.g. Dashboard, Landing Page, E-commerce or null"
  }
}
If NO templates found, return {"listings": []}.
PAGE TEXT:
""",
}

# Default prompt for unknown industries — generic enough to work for anything
_GENERIC_EXTRACTION_PROMPT = """\
You are a data extraction assistant. Given text scraped from a business webpage, \
extract all listed items (products, services, menu items, properties, etc.).

Return JSON: {"listings": [...]}. Each element:
{
  "title": "item name or title",
  "status": "active | inactive",
  "description": "string or null",
  "price": float or null,
  "price_display": "formatted price string or null",
  "currency": "USD",
  "street": null, "suburb": null, "state": null, "postcode": null,
  "attributes": {}
}
If NO items found, return {"listings": []}.
PAGE TEXT:
"""

# Max tokens for a page extraction response
_EXTRACT_MAX_TOKENS = _settings.LLM_EXTRACT_MAX_TOKENS


def get_extraction_prompt(industry: str, custom_prompt: Optional[str] = None) -> str:
    """Return the extraction prompt for the given industry.
    custom_prompt (from IndustrySchema.extraction_prompt) takes priority."""
    if custom_prompt and custom_prompt.strip():
        return custom_prompt
    return _DEFAULT_EXTRACTION_PROMPTS.get(industry, _GENERIC_EXTRACTION_PROMPT)


def _try_parse_listings_json(raw: str) -> Optional[List[Dict[str, Any]]]:
    """
    Attempt to parse a listings JSON response robustly.

    Tries, in order:
      1. Direct json.loads (handles json_object mode: {"listings": [...]})
      2. Strip markdown fences then json.loads
      3. Regex extraction of the first [...] array in the string
    Returns the list on success, None on total failure.
    """
    import json

    text = raw.strip()

    # ── Attempt 1: clean json.loads ───────────────────────────────────────
    for candidate in (text, text.split("\n", 1)[-1].rsplit("```", 1)[0].strip() if text.startswith("```") else None):
        if candidate is None:
            continue
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict):
                # json_object mode wraps in {"listings": [...]}
                for key in ("listings", "results", "data", "properties"):
                    if isinstance(parsed.get(key), list):
                        return parsed[key]
            return None
        except json.JSONDecodeError:
            continue

    # ── Attempt 2: extract first [...] block with regex ───────────────────
    import re
    match = re.search(r"\[.*?\]", text, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group())
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass

    return None


async def extract_listings_from_page(
    page_text: str,
    openai_service: Any,
    source_url: Optional[str] = None,
    industry: str = "real_estate",
    custom_prompt: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Ask the LLM to extract structured listing data from a scraped page.
    Industry-aware: uses the prompt from IndustrySchema (custom_prompt) if
    provided, otherwise falls back to the built-in default for that industry.

    Never raises — returns [] on any failure.
    """
    cleaned = clean_html_text(page_text)
    if len(cleaned.strip()) < 100:
        return []

    prompt = get_extraction_prompt(industry, custom_prompt) + cleaned[:10000]

    try:
        raw = await openai_service.openai_call_json(
            messages=[{"role": "user", "content": prompt}],
            system_instructions=(
                f"You extract structured {industry.replace('_', ' ')} item data from webpage text. "
                "Always return a JSON object with a 'listings' key containing an array."
            ),
            max_tokens=_EXTRACT_MAX_TOKENS,
            max_retries=0,  # background task — fail fast, don't block other pages
        )

        listings = _try_parse_listings_json(raw)
        if listings is None:
            logger.warning(
                "Listing extraction: unparseable JSON for %s. raw=%r", source_url, raw[:200]
            )
            return []

        for item in listings:
            if source_url:
                item.setdefault("raw_data", {})["source_url"] = source_url
            # Ensure attributes key always exists
            item.setdefault("attributes", {})

        logger.info(
            "Listing extraction: found %d items from %s (industry=%s)",
            len(listings), source_url or "page", industry,
        )
        return listings

    except Exception as exc:
        logger.warning("Listing extraction failed for %s: %s", source_url, exc)
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

_DEFAULT_FILE_PARSE_PROMPTS: Dict[str, str] = {
    "real_estate": """\
You are a real-estate data cleaning and extraction assistant.

Below is tabular data from an uploaded property listing file. Each row is one property.
The first line is headers; the rest are data rows separated by tabs.

The table contains exactly {row_count} row(s). Return exactly {row_count} element(s) in order.

TASKS:
1. Map each row to the output schema.
2. Clean text: strip noise (***,!!!,@@,##,---), trim whitespace, Title Case titles.
   If title is null/gibberish after cleaning → "Property Listing".
3. Fix geography: correct state to match suburb (Sydney→NSW, Melbourne→VIC, etc.).
4. Fix price/type: price_display with "per week"/"pw"/"/wk" → listing_type "rent".
5. Null out: invalid postcodes, negative values, zero prices.

OUTPUT — JSON array, each element:
{{
  "title": "string",
  "status": "active | sold | leased | inactive",
  "description": "string or null",
  "price": float or null,
  "price_display": "string or null",
  "currency": "USD",
  "street": "string or null",
  "suburb": "string or null",
  "state": "2–3 letter code or null",
  "postcode": "4-digit string or null",
  "attributes": {{
    "listing_type": "sale | rent",
    "bedrooms": integer or null,
    "bathrooms": integer or null,
    "garages": integer or null,
    "land_sqm": float or null,
    "house_sqm": float or null,
    "has_pool": true | false
  }}
}}

Return ONLY the JSON array. No markdown, no explanation.

TABLE DATA:
""",
    "restaurant": """\
You are a restaurant menu data cleaning assistant.

Below is tabular data from an uploaded menu file. Each row is one menu item.
The first line is headers; the rest are data rows separated by tabs.

The table contains exactly {row_count} row(s). Return exactly {row_count} element(s) in order.

TASKS:
1. Map each row to the output schema.
2. Clean text: strip noise, trim whitespace, Title Case item names.
3. Null out: negative prices, zero prices.

OUTPUT — JSON array, each element:
{{
  "title": "string — item name",
  "status": "available | unavailable | seasonal",
  "description": "string or null",
  "price": float or null,
  "price_display": "string or null",
  "currency": "USD",
  "street": null, "suburb": null, "state": null, "postcode": null,
  "attributes": {{
    "category": "string or null",
    "dietary_tags": ["vegan", "halal", ...] or [],
    "spice_level": "mild | medium | hot | extra_hot or null",
    "preparation_time_minutes": integer or null
  }}
}}

Return ONLY the JSON array. No markdown, no explanation.

TABLE DATA:
""",
    "ecommerce": """\
You are an e-commerce product data cleaning assistant.

Below is tabular data from an uploaded product file. Each row is one product.
The first line is headers; the rest are data rows separated by tabs.

The table contains exactly {row_count} row(s). Return exactly {row_count} element(s) in order.

TASKS:
1. Map each row to the output schema.
2. Clean text: strip noise, trim whitespace, Title Case product names.
3. Null out: negative prices, zero prices, invalid quantities.

OUTPUT — JSON array, each element:
{{
  "title": "string — product name",
  "status": "active | out_of_stock | discontinued",
  "description": "string or null",
  "price": float or null,
  "price_display": "string or null",
  "currency": "USD",
  "street": null, "suburb": null, "state": null, "postcode": null,
  "attributes": {{
    "sku": "string or null",
    "brand": "string or null",
    "category": "string or null",
    "condition": "new | used | refurbished or null",
    "stock_quantity": integer or null,
    "weight_kg": float or null
  }}
}}

Return ONLY the JSON array. No markdown, no explanation.

TABLE DATA:
""",
}

_GENERIC_FILE_PARSE_PROMPT = """\
You are a data cleaning assistant.

Below is tabular data from an uploaded file. Each row is one item.
The first line is headers; the rest are data rows separated by tabs.

The table contains exactly {row_count} row(s). Return exactly {row_count} element(s) in order.

OUTPUT — JSON array, each element:
{{
  "title": "string",
  "status": "active",
  "description": "string or null",
  "price": float or null,
  "price_display": "string or null",
  "currency": "USD",
  "street": null, "suburb": null, "state": null, "postcode": null,
  "attributes": {{}}
}}

Return ONLY the JSON array. No markdown, no explanation.

TABLE DATA:
"""

# Rows per LLM call — keeps each request under ~3k tokens.
_LLM_BATCH_SIZE = _settings.LLM_FILE_PARSE_BATCH_SIZE


def get_file_parse_prompt(industry: str, custom_prompt: Optional[str] = None) -> str:
    """Return the file parse prompt for the given industry."""
    if custom_prompt and custom_prompt.strip():
        return custom_prompt
    return _DEFAULT_FILE_PARSE_PROMPTS.get(industry, _GENERIC_FILE_PARSE_PROMPT)


async def parse_listings_from_table(
    rows: List[Dict[str, Any]],
    openai_service: Any,
    batch_size: int = _LLM_BATCH_SIZE,
    industry: str = "real_estate",
    custom_prompt: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Use the LLM to normalise and structure raw rows from a CSV/Excel file.
    Industry-aware: uses the prompt from IndustrySchema if provided.

    Batches are fired concurrently — total wall-clock ≈ 1 LLM call instead of N.
    On failure for any batch, falls back to the raw parsed rows.
    """
    import asyncio

    if not rows:
        return []

    prompt_template = get_file_parse_prompt(industry, custom_prompt)
    industry_label = industry.replace("_", " ")

    async def _call_llm(batch: List[Dict[str, Any]], batch_start: int) -> List[Dict[str, Any]]:
        headers = list(batch[0].keys())
        table_lines = ["\t".join(str(h) for h in headers)]
        for row in batch:
            table_lines.append("\t".join(str(row.get(h, "") or "") for h in headers))
        table_text = "\n".join(table_lines)

        prompt = prompt_template.format(row_count=len(batch)) + table_text

        try:
            raw = await openai_service.openai_call_json(
                messages=[{"role": "user", "content": prompt}],
                system_instructions=(
                    f"You extract structured {industry_label} item data from tabular data. "
                    "Return only a valid JSON object with a 'listings' key containing the array."
                ),
                max_tokens=1500,
                max_retries=0,  # background task — fail fast
            )

            parsed = _try_parse_listings_json(raw)
            if isinstance(parsed, list):
                # Ensure every item has an attributes key
                for item in parsed:
                    item.setdefault("attributes", {})
                logger.info(
                    "LLM parsed rows %d–%d: %d items (industry=%s)",
                    batch_start, batch_start + len(batch), len(parsed), industry,
                )
                return parsed

            logger.warning(
                "LLM returned unparseable JSON for rows %d (industry=%s). raw=%r — falling back.",
                batch_start, industry, raw[:200],
            )
            return batch

        except Exception as exc:
            logger.error(
                "LLM parse error for rows %d–%d (industry=%s): %s. Falling back.",
                batch_start, batch_start + len(batch), industry, exc,
            )
            return batch

    batches = [(rows[i: i + batch_size], i) for i in range(0, len(rows), batch_size)]
    raw_results = await asyncio.gather(
        *[_call_llm(b, start) for b, start in batches],
        return_exceptions=True,
    )
    merged: list = []
    for (batch, start), result in zip(batches, raw_results):
        if isinstance(result, BaseException):
            logger.error(
                "parse_listings_from_table: batch at row %d raised unexpectedly: %s — falling back to raw rows",
                start, result,
            )
            merged.extend(batch)
        else:
            merged.extend(result)
    return merged
