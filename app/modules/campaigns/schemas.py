# app/modules/campaigns/schemas.py
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.core.enums import CampaignStatus


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class CampaignCreateRequest(BaseModel):
    """Create a new campaign for a chatbot."""

    name: str = Field(
        ..., min_length=1, max_length=255,
        description="Human-readable campaign name. E.g. 'Contact Us Campaign'.",
    )
    description: Optional[str] = Field(
        default=None,
        description="Internal notes — not shown to visitors.",
    )
    url_patterns: List[str] = Field(
        default_factory=list,
        description=(
            "List of URL substrings that trigger this campaign. "
            "Case-insensitive substring match against the visitor's page URL. "
            "E.g. [\"/contact-us\", \"/get-in-touch\"]. "
            "Leave empty if you want to use is_default=true as a catch-all."
        ),
    )
    is_default: bool = Field(
        default=False,
        description=(
            "When true, this campaign fires on any page that no other campaign's "
            "url_patterns match. Only one campaign per chatbot should be default."
        ),
    )
    sort_order: int = Field(
        default=0,
        description="Priority when multiple campaigns match the same URL. Lower = higher priority.",
    )
    welcome_message: Optional[str] = Field(
        default=None,
        description=(
            "First message shown in the chatbot widget when a visitor lands on a page "
            "matched by this campaign. Overrides the chatbot-level welcome message. "
            "Leave blank to use the chatbot's default welcome message."
        ),
    )
    prompt_overlay: Optional[str] = Field(
        default=None,
        max_length=4000,
        description=(
            "Campaign-specific instructions injected into the AI system prompt. "
            "Sits between the chatbot's base personality and the live RAG context. "
            "Example: 'This is the Contact Us campaign. The visitor is likely interested "
            "in speaking to someone. Make it easy, warm, and quick to get their details.'"
        ),
    )


class CampaignUpdateRequest(BaseModel):
    """Partial update — all fields optional."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    url_patterns: Optional[List[str]] = None
    is_default: Optional[bool] = None
    sort_order: Optional[int] = None
    welcome_message: Optional[str] = None
    prompt_overlay: Optional[str] = Field(default=None, max_length=4000)


class CampaignStatusRequest(BaseModel):
    """Activate / deactivate / reset to draft."""

    status: CampaignStatus = Field(
        ...,
        description="New status: 'active', 'inactive', or 'draft'.",
    )


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class CampaignResponse(BaseModel):
    """Full campaign row returned by all CRUD endpoints."""

    public_id: str
    chatbot_public_id: str = Field(
        description="Public ID of the parent ChatbotConfig.",
    )
    name: str
    description: Optional[str]
    status: CampaignStatus
    url_patterns: List[str]
    is_default: bool
    sort_order: int
    welcome_message: Optional[str]
    prompt_overlay: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CampaignListResponse(BaseModel):
    items: List[CampaignResponse]
    total: int
