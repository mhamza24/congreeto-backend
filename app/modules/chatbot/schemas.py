"""
app/modules/knowledge/schemas.py

Pydantic v2 schemas — request/response only, no ORM objects escape the service layer.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl


# =============================================================================
# SHARED
# =============================================================================

class OkResponse(BaseModel):
    ok: bool = True


# =============================================================================
# COMPANY PROFILE  (tenant-specific context injected into the system prompt)
# =============================================================================

class CompanyProfile(BaseModel):
    """
    Tenant company information embedded into the chatbot's system prompt.
    All fields are optional — only non-null values are rendered into the prompt.
    """
    company_name:        Optional[str]       = Field(default=None, max_length=255)
    tagline:             Optional[str]       = Field(default=None, max_length=500)
    company_description: Optional[str]       = Field(default=None, max_length=2000)
    company_vision:      Optional[str]       = Field(default=None, max_length=1000)
    company_website:     Optional[str]       = Field(default=None, max_length=500)
    contact_email:       Optional[str]       = Field(default=None, max_length=255)
    contact_phone:       Optional[str]       = Field(default=None, max_length=50)
    locations:           Optional[List[str]] = Field(default=None)
    portfolio_summary:   Optional[str]       = Field(
        default=None, max_length=3000,
        description="Brief overview of the property portfolio or offerings.",
    )
    industry:            Optional[str]       = Field(default="real_estate", max_length=100)
    target_audience:     Optional[str]       = Field(
        default=None, max_length=1000,
        description="Who the chatbot should speak to, e.g. 'first-home buyers, investors aged 25-45'.",
    )
    key_services:        Optional[str]       = Field(
        default=None, max_length=1000,
        description="Key services or offerings, e.g. 'residential sales, commercial leasing, property management'.",
    )
    brand_tone:          Optional[str]       = Field(
        default=None, max_length=500,
        description="Desired brand tone, e.g. 'professional and warm', 'luxury and exclusive', 'approachable'.",
    )
    area_served:         Optional[str]       = Field(
        default=None, max_length=500,
        description="Geographic area or suburbs served, e.g. 'Greater Sydney, NSW', 'Gold Coast'.",
    )


# =============================================================================
# PROMPT PERSONALITY
# =============================================================================

class PromptPersonalityResponse(BaseModel):
    """Public-facing personality overview — shown in chatbot creation UI."""
    public_id: str
    name: str
    slug: str
    description: Optional[str]
    image_url: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PromptPersonalityAdminResponse(BaseModel):
    """Full personality detail for super-admin — includes prompt content."""
    public_id: str
    name: str
    slug: str
    description: Optional[str]
    image_url: Optional[str] = None
    system_prompt: Optional[str] = None
    personality_content: Dict[str, Any]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PromptPersonalityCreateRequest(BaseModel):
    name: str = Field(max_length=100)
    slug: str = Field(max_length=100, description="URL-safe unique key, e.g. 'aria-sales'.")
    description: Optional[str] = None
    system_prompt: str = Field(
        description="Plain-text system prompt. Write naturally — use /ai-enhance to improve it."
    )
    image_url: Optional[str] = Field(default=None, max_length=2048)
    is_active: bool = Field(default=True)


class PromptPersonalityUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=100)
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    image_url: Optional[str] = Field(default=None, max_length=2048)
    is_active: Optional[bool] = None


class AiEnhanceRequest(BaseModel):
    """Optional hint to guide the AI enhancement."""
    goal: Optional[str] = Field(
        default=None,
        description=(
            "Optional description of the desired outcome, e.g. "
            "'make her more sales-driven and push towards closing'."
        ),
    )


class AiEnhanceResponse(BaseModel):
    enhanced_prompt: str
    original_prompt: str


# =============================================================================
# CHATBOT CONFIG
# =============================================================================

class ChatbotCreateRequest(BaseModel):
    name: str = Field(max_length=255, default="My Chatbot")
    identity: str = Field(default="website")
    welcome_message: Optional[str] = None
    auto_close_minutes: int = Field(default=15, ge=1, le=1440)
    allowed_domains: List[str] = Field(default_factory=list)
    branding: Dict[str, Any] = Field(default_factory=dict)
    lead_capture_config: Dict[str, Any] = Field(default_factory=dict)
    company_profile: Optional[CompanyProfile] = Field(
        default=None,
        description="Company information used to personalise the system prompt.",
    )
    prompt_personality_slug: str = Field(
        description="Personality template slug — must match an active personality in the DB (e.g. 'leo', 'aria'). Required.",
    )
    custom_instructions: Optional[str] = Field(
        default=None,
        description=(
            "Additional instructions appended after the base personality. "
            "Use this to override tone, focus, or behaviour for this specific chatbot. "
            "e.g. 'Be more sales-driven and always push towards booking a viewing.'"
        ),
    )
    industry: str = Field(
        default="real_estate",
        max_length=100,
        description="Industry this chatbot serves (e.g. 'real_estate', 'restaurant', 'ecommerce'). "
                    "Drives listing extraction prompts and RAG search behaviour.",
    )
    listing_filter_config: Dict[str, Any] = Field(
        default_factory=dict,
        description="Industry-specific listing filter overrides (e.g. {'listing_type': 'rent'} for RE).",
    )
    model: Optional[str] = Field(
        default=None,
        max_length=64,
        description=(
            "OpenAI chat model override. Leave NULL to use the platform default "
            "(gpt-4o-mini). Premium values (gpt-4.1) require an active EXTRA_PREMIUM_MODEL "
            "add-on on the tenant's subscription; otherwise the API returns 402."
        ),
    )


class ChatbotUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=255)
    welcome_message: Optional[str] = None
    auto_close_minutes: Optional[int] = Field(default=None, ge=1, le=1440)
    allowed_domains: Optional[List[str]] = None
    branding: Optional[Dict[str, Any]] = None
    lead_capture_config: Optional[Dict[str, Any]] = None
    company_profile: Optional[CompanyProfile] = Field(
        default=None,
        description="Update company profile. Triggers system prompt regeneration.",
    )
    prompt_personality_slug: Optional[str] = Field(
        default=None,
        description="Switch personality. Triggers system prompt regeneration.",
    )
    custom_instructions: Optional[str] = Field(
        default=None,
        description=(
            "Override instructions appended after the base personality. "
            "Set to empty string '' to clear existing instructions. "
            "Triggers system prompt regeneration."
        ),
    )
    industry: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Change the industry this chatbot serves.",
    )
    listing_filter_config: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Update industry-specific listing filter overrides.",
    )
    model: Optional[str] = Field(
        default=None,
        max_length=64,
        description=(
            "Switch chat model. Premium values (gpt-4.1) require an active "
            "EXTRA_PREMIUM_MODEL add-on on the tenant's subscription."
        ),
    )


class ChatbotActivateRequest(BaseModel):
    """Explicit intent — user is trying to go live."""
    status: str = Field("active", pattern="^(active|inactive|draft)$")


class ChatbotResponse(BaseModel):
    public_id: str
    name: str
    status: str
    iframe_token: str
    identity: str
    system_prompt_template: Optional[str]
    welcome_message: Optional[str]
    rag_enabled: bool
    industry: str
    listing_filter_config: Dict[str, Any]
    auto_close_minutes: int
    allowed_domains: List[str]
    branding: Dict[str, Any]
    lead_capture_config: Dict[str, Any]
    company_profile: Dict[str, Any]
    prompt_personality_id: Optional[int]
    custom_instructions: Optional[str] = None
    model: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# =============================================================================
# WIDGET THEME
# =============================================================================

class ThemeCreateRequest(BaseModel):
    name: str = Field(default="Default Theme", max_length=100)
    is_paid_theme: bool = Field(default=False, description="True for premium themes requiring the Premium Widget add-on.")
    colors: Dict[str, Any] = Field(default_factory=dict)
    typography: Dict[str, Any] = Field(default_factory=dict)
    assets: Dict[str, Any] = Field(default_factory=dict)
    layout: Dict[str, Any] = Field(default_factory=dict)


class ThemeUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=100)
    colors: Optional[Dict[str, Any]] = None
    typography: Optional[Dict[str, Any]] = None
    assets: Optional[Dict[str, Any]] = None
    layout: Optional[Dict[str, Any]] = None


class ThemeResponse(BaseModel):
    public_id: str
    name: str
    is_active: bool
    is_paid_theme: bool
    colors: Dict[str, Any]
    typography: Dict[str, Any]
    assets: Dict[str, Any]
    layout: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# =============================================================================
# ASSET UPLOAD
# =============================================================================

class AssetUploadResponse(BaseModel):
    public_id: str
    asset_type: str
    file_name: str
    content_type: str
    file_size_bytes: int
    serve_url: str  # e.g. /knowledge/assets/{public_id}
    created_at: datetime

    model_config = {"from_attributes": True}


# =============================================================================
# MANUAL Q&A ENTRY
# =============================================================================

class ManualEntryCreateRequest(BaseModel):
    title: str = Field(max_length=500, description="Label for this entry (e.g. question text)")
    content: str = Field(min_length=1, description="The knowledge content / answer text")


# =============================================================================
# KNOWLEDGE SOURCE
# =============================================================================

class KnowledgeSourceCreateRequest(BaseModel):
    type: str = Field(pattern="^(website|document|manual_qa)$")
    name: str = Field(min_length=1, max_length=255)
    config: Dict[str, Any] = Field(default_factory=dict)


class KnowledgeSourceUpdateRequest(BaseModel):
    type: Optional[str] = Field(default=None, pattern="^(website|document|manual_qa)$")
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    config: Optional[Dict[str, Any]] = None


class KnowledgeSourceResponse(BaseModel):
    public_id: str
    type: str
    name: str
    status: str
    config: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# =============================================================================
# CRAWL JOB  (Option A — paste URLs)
# =============================================================================

class CrawlJobCreateRequest(BaseModel):
    urls: List[str] = Field(
        min_length=1,
        description="One or more base URLs to crawl.",
    )


class CrawlJobResponse(BaseModel):
    public_id: str
    base_url: str
    status: str
    pages_found: int
    pages_processed: int
    pages_failed: int
    error_message: Optional[str]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


class CrawlJobListResponse(BaseModel):
    jobs: List[CrawlJobResponse]


# =============================================================================
# DOCUMENT  (Option B — upload PDF)
# =============================================================================

class DocumentResponse(BaseModel):
    public_id: str
    file_name: str
    file_type: str
    file_size_bytes: int
    storage_path: Optional[str]
    status: str
    chunk_count: int
    page_count: Optional[int]
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentListResponse(BaseModel):
    documents: List[DocumentResponse]


# =============================================================================
# DOCUMENT CHUNK
# =============================================================================

class ChunkResponse(BaseModel):
    chunk_index: int
    content: str
    chunk_metadata: Dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


# =============================================================================
# RAG  (similarity search — used internally by chat service)
# =============================================================================

class RAGQueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    chatbot_public_id: str
    top_k: int = Field(default=5, ge=1, le=20)


class RAGChunkResult(BaseModel):
    content: str
    chunk_metadata: Dict[str, Any]
    chunk_index: int
    document_id: int = 0  # sentinel 0 = listing hit (no document row)


class RAGQueryResponse(BaseModel):
    chunks: List[RAGChunkResult]
    total: int


# =============================================================================
# LIVE LINK SCRAPPER  (existing — kept for backwards compat)
# =============================================================================

class liveLinkScrapperRequest(BaseModel):
    link: Union[str, List[str], Dict[str, Any]] = Field(
        description="Live link for scrapping data",
    )


class liveLinkScrapperResponse(BaseModel):
    id: str = Field(description="Celery task ID")
    status: str = Field(description="pending | started | success | failure")

# =============================================================================
# ADMIN
# =============================================================================

class AdminChatbotStatusRequest(BaseModel):
    status: str = Field(pattern="^(draft|active|inactive)$")


# =============================================================================
# PUBLIC EMBED — returned for unauthenticated iframe_token requests
# =============================================================================

class EmbedTheme(BaseModel):
    name: str
    colors: Dict[str, Any]
    typography: Dict[str, Any]
    assets: Dict[str, Any]
    layout: Dict[str, Any]

    model_config = {"from_attributes": True}


class ChatbotEmbedResponse(BaseModel):
    """
    Returned by GET /chatbot/embed/{iframe_token} — no auth required.
    Contains everything the widget needs to render itself.
    """
    iframe_token: str
    name: str
    status: str
    welcome_message: Optional[str]
    auto_close_minutes: int
    branding: Dict[str, Any]
    lead_capture_config: Dict[str, Any]
    company_profile: Dict[str, Any]
    active_theme: Optional[EmbedTheme] = None

    model_config = {"from_attributes": True}
