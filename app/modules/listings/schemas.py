from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, Field


class ListingCreateRequest(BaseModel):
    title: str = Field(max_length=500)
    listing_type: str = Field(pattern="^(sale|rent)$")
    status: str = Field(default="active", pattern="^(active|inactive|sold|leased)$")
    description: Optional[str] = None
    price: Optional[float] = None
    price_display: Optional[str] = Field(default=None, max_length=100)
    currency: str = Field(default="AUD", max_length=3)
    street: Optional[str] = Field(default=None, max_length=255)
    suburb: Optional[str] = Field(default=None, max_length=100)
    state: Optional[str] = Field(default=None, max_length=50)
    postcode: Optional[str] = Field(default=None, max_length=10)
    country: str = Field(default="AU", max_length=5)
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    garages: Optional[int] = None
    land_sqm: Optional[float] = None
    house_sqm: Optional[float] = None
    has_pool: bool = False
    media: List[Any] = Field(default_factory=list)


class ListingUpdateRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=500)
    listing_type: Optional[str] = Field(default=None, pattern="^(sale|rent)$")
    status: Optional[str] = Field(default=None, pattern="^(active|inactive|sold|leased)$")
    description: Optional[str] = None
    price: Optional[float] = None
    price_display: Optional[str] = Field(default=None, max_length=100)
    currency: Optional[str] = Field(default=None, max_length=3)
    street: Optional[str] = Field(default=None, max_length=255)
    suburb: Optional[str] = Field(default=None, max_length=100)
    state: Optional[str] = Field(default=None, max_length=50)
    postcode: Optional[str] = Field(default=None, max_length=10)
    country: Optional[str] = Field(default=None, max_length=5)
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    garages: Optional[int] = None
    land_sqm: Optional[float] = None
    house_sqm: Optional[float] = None
    has_pool: Optional[bool] = None
    media: Optional[List[Any]] = None


class ListingResponse(BaseModel):
    public_id: str
    source: str
    listing_type: str
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
    country: str
    bedrooms: Optional[int]
    bathrooms: Optional[int]
    garages: Optional[int]
    land_sqm: Optional[float]
    house_sqm: Optional[float]
    has_pool: bool
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
    status: str
    total_rows: int
    processed_rows: int
    error_message: Optional[str]

    model_config = {"from_attributes": True}
