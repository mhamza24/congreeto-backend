from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


_STATUS_RE = re.compile(r"^[a-z][a-z0-9_]{0,49}$")


class ListingCreateRequest(BaseModel):
    """
    Generic listing create request — works for any industry.

    industry    : must match a row in industry_schemas.industry
    status      : any lowercase_snake_case string (validated against industry
                  schema at the service layer if strict mode is on)
    attributes  : industry-specific fields — validated at service layer
                  against IndustrySchema.attributes_schema
    """
    industry: str = Field(
        default="real_estate",
        max_length=100,
        description="Industry slug, e.g. 'real_estate', 'restaurant', 'ecommerce'.",
    )
    status: str = Field(
        default="active",
        max_length=50,
        description="Lifecycle status. Industry-defined (e.g. 'active', 'sold', 'out_of_stock').",
    )
    title: str = Field(max_length=500)
    description: Optional[str] = None
    price: Optional[float] = None
    price_display: Optional[str] = Field(default=None, max_length=100)
    currency: str = Field(default="USD", max_length=3)

    # Location — optional for all industries
    street: Optional[str] = Field(default=None, max_length=255)
    suburb: Optional[str] = Field(default=None, max_length=100)
    state: Optional[str] = Field(default=None, max_length=50)
    postcode: Optional[str] = Field(default=None, max_length=10)
    country: Optional[str] = Field(default=None, max_length=5)

    # Industry-specific fields
    attributes: Dict[str, Any] = Field(
        default_factory=dict,
        description="Industry-specific fields. See IndustrySchema.attributes_schema for the shape.",
    )
    media: List[Any] = Field(default_factory=list)

    @field_validator("industry")
    @classmethod
    def _validate_industry(cls, v: str) -> str:
        if not re.match(r"^[a-z][a-z0-9_]{0,99}$", v):
            raise ValueError("industry must be lowercase_snake_case, max 100 chars")
        return v

    @field_validator("status")
    @classmethod
    def _validate_status(cls, v: str) -> str:
        if not _STATUS_RE.match(v):
            raise ValueError("status must be lowercase_snake_case, max 50 chars")
        return v


class ListingUpdateRequest(BaseModel):
    status: Optional[str] = Field(default=None, max_length=50)
    title: Optional[str] = Field(default=None, max_length=500)
    description: Optional[str] = None
    price: Optional[float] = None
    price_display: Optional[str] = Field(default=None, max_length=100)
    currency: Optional[str] = Field(default=None, max_length=3)
    street: Optional[str] = Field(default=None, max_length=255)
    suburb: Optional[str] = Field(default=None, max_length=100)
    state: Optional[str] = Field(default=None, max_length=50)
    postcode: Optional[str] = Field(default=None, max_length=10)
    country: Optional[str] = Field(default=None, max_length=5)
    attributes: Optional[Dict[str, Any]] = None
    media: Optional[List[Any]] = None

    @field_validator("status")
    @classmethod
    def _validate_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _STATUS_RE.match(v):
            raise ValueError("status must be lowercase_snake_case, max 50 chars")
        return v


class ListingResponse(BaseModel):
    """
    Consistent response shape for all industries.

    The `attributes` dict contains all industry-specific fields (bedrooms for
    RE, category for restaurant, sku for ecommerce, etc.).  The frontend reads
    `industry` to know which keys to expect inside `attributes`.
    """
    public_id: str
    industry: str
    source: str
    status: str
    title: str
    description: Optional[str]
    price: Optional[float]
    price_display: Optional[str]
    currency: str
    street: Optional[str]
    suburb: Optional[str]
    state: Optional[str]
    postcode: Optional[str]
    country: Optional[str]
    attributes: Dict[str, Any]
    media: List[Any]
    listed_at: Optional[datetime]
    updated_at: datetime

    model_config = {"from_attributes": True}


class ListingImportResponse(BaseModel):
    imported: int
    filename: str


class ListingUploadJobResponse(BaseModel):
    public_id: str
    filename: str
    file_type: str
    industry: str
    status: str
    total_rows: int
    processed_rows: int
    error_message: Optional[str]

    model_config = {"from_attributes": True}
