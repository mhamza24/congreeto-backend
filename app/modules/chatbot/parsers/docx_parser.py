# app/modules/chatbot/parsers/docx_parser.py
"""
Word document (.docx) parser.

Extracts text paragraph by paragraph and groups them into logical pages
(every PARAGRAPHS_PER_PAGE paragraphs = 1 page) so the downstream
chunk_pages() helper works identically to the PDF pipeline.
"""
from __future__ import annotations

import io
from typing import Any

import docx

PARAGRAPHS_PER_PAGE = 30  # tune to taste


def _parse_docx(file_bytes: bytes) -> dict[str, Any]:
    """
    Returns the same shape as _parse_pdf:
    {
        "total_pages": int,
        "pages": [
            {"page_number": int, "text": str, "tables": []},
            ...
        ]
    }
    """
    doc = docx.Document(io.BytesIO(file_bytes))

    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]

    # Group into pseudo-pages
    pages = []
    for i in range(0, max(len(paragraphs), 1), PARAGRAPHS_PER_PAGE):
        chunk = paragraphs[i: i + PARAGRAPHS_PER_PAGE]
        pages.append({
            "page_number": len(pages) + 1,
            "text": "\n".join(chunk),
            "tables": [],
        })

    if not pages:
        pages = [{"page_number": 1, "text": "", "tables": []}]

    return {"total_pages": len(pages), "pages": pages}


def _parse_txt(file_bytes: bytes) -> dict[str, Any]:
    """
    Plain-text files. Decode → split into pseudo-pages by line count.
    """
    text = file_bytes.decode("utf-8", errors="replace")
    lines = [ln for ln in text.splitlines() if ln.strip()]

    pages = []
    for i in range(0, max(len(lines), 1), PARAGRAPHS_PER_PAGE):
        chunk = lines[i: i + PARAGRAPHS_PER_PAGE]
        pages.append({
            "page_number": len(pages) + 1,
            "text": "\n".join(chunk),
            "tables": [],
        })

    if not pages:
        pages = [{"page_number": 1, "text": text, "tables": []}]

    return {"total_pages": len(pages), "pages": pages}
