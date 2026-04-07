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
# CHATBOT CONFIG
# =============================================================================

class ChatbotCreateRequest(BaseModel):
    name: str = Field(max_length=255, default="My Chatbot")
    identity: str = Field(default="website")
    system_prompt_template: Optional[str] = None
    welcome_message: Optional[str] = None
    auto_close_minutes: int = Field(default=15, ge=1, le=1440)
    allowed_domains: List[str] = Field(default_factory=list)
    branding: Dict[str, Any] = Field(default_factory=dict)
    lead_capture_config: Dict[str, Any] = Field(default_factory=dict)


class ChatbotUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=255)
    system_prompt_template: Optional[str] = None
    welcome_message: Optional[str] = None
    auto_close_minutes: Optional[int] = Field(default=None, ge=1, le=1440)
    allowed_domains: Optional[List[str]] = None
    branding: Optional[Dict[str, Any]] = None
    lead_capture_config: Optional[Dict[str, Any]] = None


class ChatbotActivateRequest(BaseModel):
    """Explicit intent — user is trying to go live."""
    status: str = Field("active", pattern="^(active|inactive|draft)$")


class ChatbotResponse(BaseModel):
    id: int
    public_id: str
    tenant_id: int
    name: str
    status: str
    iframe_token: str
    identity: str
    system_prompt_template: Optional[str]
    welcome_message: Optional[str]
    rag_enabled: bool
    auto_close_minutes: int
    allowed_domains: List[str]
    branding: Dict[str, Any]
    lead_capture_config: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# =============================================================================
# WIDGET THEME
# =============================================================================

class ThemeCreateRequest(BaseModel):
    name: str = Field(default="Default Theme", max_length=100)
    colors: Dict[str, Any] = Field(default_factory=dict)
    typography: Dict[str, Any] = Field(default_factory=dict)
    assets: Dict[str, Any] = Field(default_factory=dict)
    layout: Dict[str, Any] = Field(default_factory=dict)


class ThemeResponse(BaseModel):
    id: int
    public_id: str
    chatbot_config_id: int
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
# KNOWLEDGE SOURCE
# =============================================================================

class KnowledgeSourceCreateRequest(BaseModel):
    type: str = Field(pattern="^(website|document|manual_qa)$")
    name: str = Field(max_length=255)
    config: Dict[str, Any] = Field(default_factory=dict)


class KnowledgeSourceResponse(BaseModel):
    id: int
    public_id: str
    tenant_id: int
    chatbot_config_id: int
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
    id: int
    public_id: str
    knowledge_source_id: int
    tenant_id: int
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
    id: int
    public_id: str
    knowledge_source_id: int
    tenant_id: int
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
    id: int
    document_id: int
    tenant_id: int
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
    document_id: int
    chunk_index: int


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