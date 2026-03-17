# app/modules/inquiries/schemas.py
from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List
from datetime import datetime
from enum import Enum
from uuid import UUID
from app.modules.inquiries.models import InquiryStatus


# ---------------------------------------------------------------------------
# Shared / primitives
# ---------------------------------------------------------------------------

class InquiryStatusEnum(str, Enum):
    submitted = "submitted"
    reviewed = "reviewed"
    contacted = "contacted"
    qualified = "qualified"
    converted = "converted"
    archived = "archived"


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class GeneralInquiryCreateRequest(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    company_name: Optional[str] = None
    subject: str = Field(..., min_length=1, max_length=200)
    message: str = Field(..., min_length=1, max_length=5000)


class DemoInquiryCreateRequest(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    company_name: str = Field(..., min_length=1, max_length=200)
    company_website: Optional[str] = None
    property_sectors: Optional[List[str]] = Field(default_factory=list)
    states: Optional[List[str]] = Field(default_factory=list)
    message: Optional[str] = Field(None, max_length=5000)


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class GeneralInquiryResponse(BaseModel):
    public_id: str = Field(..., description="Public inquiry ID (uuid7).")
    first_name: str
    last_name: str
    email: EmailStr
    company_name: Optional[str]
    subject: str
    message: str
    status: InquiryStatusEnum
    created_at: datetime

    class Config:
        from_attributes = True


class DemoInquiryResponse(BaseModel):
    public_id: str = Field(..., description="Public inquiry ID (uuid7).")
    first_name: str
    last_name: str
    email: EmailStr
    company_name: str
    company_website: Optional[str]
    property_sectors: List[str]
    states: List[str]
    message: Optional[str]
    status: InquiryStatusEnum
    created_at: datetime

    class Config:
        from_attributes = True
