"""
app/modules/chatbot/parsers/excel_parser.py

Parse an Excel (.xlsx) file where each row is a property listing.

Expected columns (case-insensitive, order-independent):
  title, type/listing_type, status, description,
  price, price_display, currency,
  street, suburb, state, postcode, country,
  bedrooms, bathrooms, garages, land_sqm, house_sqm, has_pool

Unknown columns are stored in raw_data for traceability.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# Map of accepted header aliases → canonical field name
_HEADER_MAP: Dict[str, str] = {
    "title": "title",
    "name": "title",
    "property": "title",
    "type": "listing_type",
    "listing_type": "listing_type",
    "property_type": "listing_type",
    "status": "status",
    "description": "description",
    "summary": "description",
    "price": "price",
    "price_display": "price_display",
    "price display": "price_display",
    "asking price": "price_display",
    "currency": "currency",
    "street": "street",
    "address": "street",
    "suburb": "suburb",
    "city": "suburb",
    "state": "state",
    "postcode": "postcode",
    "zip": "postcode",
    "country": "country",
    "bedrooms": "bedrooms",
    "beds": "bedrooms",
    "bed": "bedrooms",
    "bathrooms": "bathrooms",
    "baths": "bathrooms",
    "bath": "bathrooms",
    "garages": "garages",
    "garage": "garages",
    "car spaces": "garages",
    "land_sqm": "land_sqm",
    "land sqm": "land_sqm",
    "land size": "land_sqm",
    "house_sqm": "house_sqm",
    "house sqm": "house_sqm",
    "house size": "house_sqm",
    "has_pool": "has_pool",
    "pool": "has_pool",
}

_INT_FIELDS = {"bedrooms", "bathrooms", "garages"}
_FLOAT_FIELDS = {"price", "land_sqm", "house_sqm"}
_BOOL_FIELDS = {"has_pool"}


def _normalise_header(raw: str) -> str:
    return str(raw).strip().lower().replace("-", "_").replace("  ", " ")


def _cast(field: str, value: Any) -> Any:
    if value is None or str(value).strip() == "":
        return None
    try:
        if field in _INT_FIELDS:
            return int(float(str(value)))
        if field in _FLOAT_FIELDS:
            cleaned = str(value).replace(",", "").replace("$", "").strip()
            return float(cleaned)
        if field in _BOOL_FIELDS:
            return str(value).strip().lower() in ("1", "yes", "true", "y")
    except (ValueError, TypeError):
        return None
    return str(value).strip() or None


def parse_excel_listings(file_bytes: bytes) -> List[Dict[str, Any]]:
    """
    Parse an Excel workbook and return a list of listing dicts.
    Skips rows where title is empty.
    Raises ValueError if openpyxl is not installed or file is unreadable.
    """
    try:
        import openpyxl
    except ImportError:
        raise ValueError("openpyxl is required for Excel upload. Run: pip install openpyxl")

    import io
    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    except Exception as exc:
        raise ValueError(f"Could not read Excel file: {exc}")

    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []

    # First row = headers
    raw_headers = [str(h).strip() if h is not None else "" for h in rows[0]]
    canonical = [_HEADER_MAP.get(_normalise_header(h)) for h in raw_headers]

    results: List[Dict[str, Any]] = []
    for row_idx, row in enumerate(rows[1:], start=2):
        known: Dict[str, Any] = {}
        extra: Dict[str, Any] = {}

        for col_idx, cell_value in enumerate(row):
            field = canonical[col_idx] if col_idx < len(canonical) else None
            raw_header = raw_headers[col_idx] if col_idx < len(raw_headers) else f"col_{col_idx}"
            if field:
                known[field] = _cast(field, cell_value)
            else:
                if cell_value is not None:
                    extra[raw_header] = cell_value

        title = known.get("title")
        if not title:
            logger.debug(f"Excel row {row_idx}: skipping — no title")
            continue

        listing_type = (known.get("listing_type") or "sale").lower()
        if listing_type not in ("sale", "rent"):
            listing_type = "sale"

        known["listing_type"] = listing_type
        known["raw_data"] = extra
        results.append(known)

    logger.info(f"Excel parsed: {len(results)} listing rows")
    return results
