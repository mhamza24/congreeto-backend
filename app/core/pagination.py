"""
app/core/pagination.py

Reusable keyset / cursor pagination primitives.

Why keyset (vs OFFSET)
──────────────────────
OFFSET asks Postgres to count and discard N rows on every request.
Page 50 of an audit log is 50 × page_size rows of wasted I/O.

Keyset / cursor uses an indexed lookup: "give me the next N rows whose
(sort_key, id) is strictly less than the last row I saw". The query
becomes a single index seek regardless of how deep the user has paged.

Cursor format
─────────────
The cursor is opaque to the client. Internally it is:

    base64url( "{sort_value}|{id}" )

- `sort_value` is the value of the table's natural sort column (usually
  the ISO-formatted `created_at`, but can be any sortable scalar).
- `id` is the BIGINT primary key, used as a tiebreaker so two rows with
  the same `sort_value` cannot collide.

Standard usage in a repository
──────────────────────────────
    from app.core.pagination import (
        CursorParams, CursorPage, encode_cursor, decode_cursor,
    )

    async def list_items(db, *, tenant_id, params: CursorParams):
        q = (
            select(Item)
            .where(Item.tenant_id == tenant_id)
            .order_by(Item.created_at.desc(), Item.id.desc())
            .limit(params.page_size + 1)   # fetch one extra to know if more exist
        )
        if params.cursor:
            cur_dt, cur_id = decode_cursor(params.cursor)
            q = q.where(
                or_(
                    Item.created_at < cur_dt,
                    and_(Item.created_at == cur_dt, Item.id < cur_id),
                )
            )
        rows = (await db.execute(q)).scalars().all()
        return CursorPage.build(rows, params.page_size, sort_attr="created_at")

The `+1 / strip / encode` pattern is wrapped by `CursorPage.build()` so
every endpoint stays one line.
"""

from __future__ import annotations

import base64
from datetime import datetime
from typing import Any, Callable, Generic, List, Optional, Sequence, Tuple, TypeVar

from pydantic import BaseModel, Field

# ─────────────────────────────────────────────────────────────────────────────
# Cursor encode / decode
# ─────────────────────────────────────────────────────────────────────────────

_CURSOR_SEP = "|"


def encode_cursor(sort_value: Any, item_id: int) -> str:
    """
    Encode a (sort_value, id) tuple into an opaque base64url cursor.

    `sort_value` is stringified — for datetimes we use ISO 8601 with timezone
    info preserved. The cursor is only meant to be opaque to clients; the server
    decodes it back to the same types it produced.
    """
    if isinstance(sort_value, datetime):
        rendered = sort_value.isoformat()
    else:
        rendered = str(sort_value)
    raw = f"{rendered}{_CURSOR_SEP}{item_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> Tuple[datetime, int]:
    """
    Decode a cursor back into (sort_value_as_datetime, id).

    Currently every paginated table sorts by `created_at`, so the sort value
    is always parsed as a datetime. If a future table needs a non-datetime
    sort key, add a typed variant rather than mutating this one — keeping the
    decoder narrow makes the cursor format easy to reason about.

    Raises ValueError on malformed input — the API layer should map this to
    HTTP 400 so a stale browser cursor returns a useful error message.
    """
    try:
        # Re-pad: base64url-decode tolerates missing "=" only with explicit pad
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        sort_str, id_str = raw.rsplit(_CURSOR_SEP, 1)
        return datetime.fromisoformat(sort_str), int(id_str)
    except Exception as exc:
        raise ValueError(f"Invalid pagination cursor: {cursor!r}") from exc


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic schemas
# ─────────────────────────────────────────────────────────────────────────────

T = TypeVar("T")


class CursorParams(BaseModel):
    """
    Validated query-string params for any cursor-paginated endpoint.

    `page_size` bounds are intentionally loose here — individual endpoints
    should re-bind the field with the route-specific min/max via Query().
    """
    page_size: int = Field(default=20, ge=1, le=200)
    cursor: Optional[str] = Field(default=None, max_length=512)


class CursorMeta(BaseModel):
    """Pagination metadata returned alongside `items`."""
    page_size:   int
    next_cursor: Optional[str] = Field(
        default=None,
        description=(
            "Opaque cursor — pass back as `cursor` to fetch the next page. "
            "`null` when has_next is false."
        ),
    )
    has_next:    bool = Field(
        description="True when at least one more page exists after this one.",
    )


class CursorPage(BaseModel, Generic[T]):
    """
    Standard envelope for a cursor-paginated list response.

    Use `CursorPage.build(...)` from a repository to handle the
    fetch-one-extra / strip / encode dance in a single call.
    """
    items: List[T]
    meta:  CursorMeta

    @classmethod
    def build(
        cls,
        rows: Sequence[Any],
        page_size: int,
        *,
        sort_attr: str = "created_at",
        id_attr: str = "id",
        key_fn: Optional[Callable[[Any], Tuple[Any, int]]] = None,
    ) -> "CursorPage[Any]":
        """
        Convert a list of rows (fetched with LIMIT page_size + 1) into a
        CursorPage. Trims the trailing sentinel row, sets `has_next`, and
        encodes the cursor from the last visible row.

        Works with ORM instances, Pydantic models, plain dicts, or anything
        else — by default uses getattr/dict-lookup on `sort_attr` + `id_attr`,
        but you can pass `key_fn(row) -> (sort_value, id)` for full control
        (e.g. when paging on a joined column).
        """
        has_next = len(rows) > page_size
        visible = list(rows[:page_size])

        next_cursor: Optional[str] = None
        if has_next and visible:
            last = visible[-1]
            if key_fn is not None:
                sort_val, item_id = key_fn(last)
            elif isinstance(last, dict):
                sort_val, item_id = last[sort_attr], last[id_attr]
            else:
                sort_val, item_id = getattr(last, sort_attr), getattr(last, id_attr)
            next_cursor = encode_cursor(sort_val, item_id)

        return cls(
            items=visible,
            meta=CursorMeta(
                page_size=page_size,
                next_cursor=next_cursor,
                has_next=has_next,
            ),
        )
