"""
app/modules/chatbot/parsers/csv_parser.py

Parse a CSV file where each row is a property listing.
Reuses the same column-mapping and casting logic as excel_parser.py.
"""
from __future__ import annotations

import csv
import io
import logging
from typing import Any, Dict, List

from app.modules.chatbot.parsers.excel_parser import (
    _HEADER_MAP,
    _cast,
    _normalise_header,
)

logger = logging.getLogger(__name__)


def parse_csv_listings(file_bytes: bytes) -> List[Dict[str, Any]]:
    """
    Parse a CSV file and return a list of listing dicts.
    Skips rows where title is empty.
    Raises ValueError if the file cannot be decoded or is malformed.
    """
    # Try common encodings in order
    text: str | None = None
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = file_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            continue

    if text is None:
        raise ValueError("Could not decode CSV file (tried utf-8, utf-8-bom, latin-1)")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return []

    raw_headers = list(reader.fieldnames)
    canonical = {h: _HEADER_MAP.get(_normalise_header(h)) for h in raw_headers}

    results: List[Dict[str, Any]] = []
    for row_idx, row in enumerate(reader, start=2):
        known: Dict[str, Any] = {}
        extra: Dict[str, Any] = {}

        for raw_header in raw_headers:
            field = canonical.get(raw_header)
            cell_value = row.get(raw_header)
            if field:
                known[field] = _cast(field, cell_value)
            else:
                if cell_value is not None and str(cell_value).strip():
                    extra[raw_header] = cell_value

        title = known.get("title")
        if not title:
            logger.debug(f"CSV row {row_idx}: skipping — no title")
            continue

        listing_type = (known.get("listing_type") or "sale").lower()
        if listing_type not in ("sale", "rent"):
            listing_type = "sale"

        known["listing_type"] = listing_type
        known["raw_data"] = extra
        results.append(known)

    logger.info(f"CSV parsed: {len(results)} listing rows")
    return results
