# app/modules/knowledge/models.py

from __future__ import annotations
from pgvector.sqlalchemy import Vector
from datetime import datetime

from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger, Boolean, Computed, DateTime, ForeignKey, Index,
    Integer, LargeBinary, Numeric, String, Text,
    UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db_base import Base, PublicIdMixin, TimestampMixin, SoftDeleteMixin
from app.core.enums import (
    ChatbotIdentity, ChatbotStatus, chatbot_identity_enum, chatbot_status_enum,
    SourceType, source_type_enum,
    CrawlStatus, crawl_status_enum,
    DocStatus, doc_status_enum,
    ListingSource, ListingStatus,
    listing_source_enum, listing_status_enum,
    UploadJobStatus, upload_job_status_enum,
)

if TYPE_CHECKING:
    from app.modules.tenants.models import Tenant
    from app.modules.users.models import User
    from app.modules.campaigns.models import Campaign


# =============================================================================
# INDUSTRY SCHEMAS  (one row per industry — drives scraping, embedding, insights)
# =============================================================================

class IndustrySchema(Base, TimestampMixin):
    """
    One row per supported industry (real_estate, restaurant, ecommerce, …).
    Stores all industry-specific LLM prompts and field definitions so the
    system is 100% generic — adding a new industry is a DB insert, not a
    code change.

    industry          : machine-readable slug, e.g. "real_estate"
    display_name      : human label, e.g. "Real Estate"
    listing_label     : singular noun for one item, e.g. "Property"
    listing_label_plural: plural noun, e.g. "Properties"
    attributes_schema : JSONB — field definitions used for frontend rendering
                        and LLM-output validation. Example:
                        {"bedrooms": {"type": "int", "label": "Bedrooms"},
                         "listing_type": {"type": "str", "label": "Type"}}
    extraction_prompt : LLM prompt template for extracting items from
                        scraped page text (appended with PAGE TEXT).
    file_parse_prompt : LLM prompt template for normalising rows from an
                        uploaded Excel/CSV file (appended with TABLE DATA).
    insights_prompt   : LLM prompt template for extracting structured insights
                        from a closed conversation.
    is_active         : soft-disable without deleting.
    """
    __tablename__ = "industry_schemas"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    industry: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True,
        comment="Machine-readable key, e.g. 'real_estate'. Never changes after creation."
    )
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    listing_label: Mapped[str] = mapped_column(
        String(100), nullable=False, default="Item", server_default=text("'Item'"),
        comment="Singular label shown in UI, e.g. 'Property', 'Menu Item', 'Product'."
    )
    listing_label_plural: Mapped[str] = mapped_column(
        String(100), nullable=False, default="Items", server_default=text("'Items'"),
        comment="Plural label, e.g. 'Properties', 'Menu Items', 'Products'."
    )
    attributes_schema: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"),
        comment="Field definitions for the attributes JSONB column on listings."
    )
    extraction_prompt: Mapped[str | None] = mapped_column(
        Text, nullable=True, default=None,
        comment="LLM prompt for extracting items from scraped page text."
    )
    file_parse_prompt: Mapped[str | None] = mapped_column(
        Text, nullable=True, default=None,
        comment="LLM prompt for normalising rows from an uploaded Excel/CSV file."
    )
    insights_prompt: Mapped[str | None] = mapped_column(
        Text, nullable=True, default=None,
        comment="LLM prompt for extracting structured insights from a closed conversation."
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("TRUE")
    )

    __table_args__ = (
        Index("ix_industry_schemas_industry", "industry"),
        Index("ix_industry_schemas_active", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<IndustrySchema industry={self.industry!r} label={self.listing_label!r}>"


# =============================================================================
# PROMPT PERSONALITIES  (ARIA, LEO, etc. — one row per persona)
# =============================================================================

class PromptPersonality(Base, PublicIdMixin, TimestampMixin):
    """
    Stores reusable chatbot personalities (ARIA, LEO, custom branded, etc.).
    Each ChatbotConfig points to one personality via prompt_personality_id.

    Two authoring modes:
      - system_prompt (Text): plain-text prompt written/enhanced by an admin.
        Takes precedence over personality_content when set.
      - personality_content (JSONB): structured JSON used by the legacy
        ARIA/LEO/ARIA_WEBSITE personas and the build_static_system_prompt renderer.

    image_url: resolved URL for the personality avatar.
    image_data / image_content_type: raw bytes for an uploaded image; the serve
      endpoint writes back to image_url automatically on upload.
    """
    __tablename__ = "prompt_personalities"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True,
        comment="Machine-readable key, e.g. 'aria', 'leo'. Never changes after creation."
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    personality_content: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"),
        comment="Full personality JSON (tone, rules, formatting, QA pairs, etc.)"
    )
    system_prompt: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment=(
            "Plain-text system prompt. When set, replaces personality_content "
            "rendering. Used for admin-created personalities."
        ),
    )
    image_url: Mapped[str | None] = mapped_column(
        String(2048), nullable=True,
        comment="URL of the personality avatar/icon image.",
    )
    image_data: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True,
        comment="Raw bytes of the uploaded personality image.",
    )
    image_content_type: Mapped[str | None] = mapped_column(
        String(100), nullable=True,
        comment="MIME type of the uploaded image, e.g. image/png.",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("TRUE")
    )

    chatbots: Mapped[list["ChatbotConfig"]] = relationship(
        "ChatbotConfig", back_populates="prompt_personality", lazy="noload"
    )

    __table_args__ = (
        Index("ix_prompt_personalities_slug", "slug"),
        Index("ix_prompt_personalities_active", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<PromptPersonality slug={self.slug!r} active={self.is_active}>"


# =============================================================================
# CHATBOT CONFIGS
# =============================================================================

class ChatbotConfig(Base, PublicIdMixin, TimestampMixin):
    __tablename__ = "chatbot_configs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(
        String(255), nullable=False, default="My Chatbot", server_default=text("'My Chatbot'")
    )
    status: Mapped[ChatbotStatus] = mapped_column(
        chatbot_status_enum, nullable=False,
        default=ChatbotStatus.DRAFT, server_default=text("'draft'")
    )
    iframe_token: Mapped[str] = mapped_column(
        String(36), nullable=False, unique=True,
        comment="Public embed key (uuid7). Never expose tenant_id in widget URL."
    )
    identity: Mapped[ChatbotIdentity] = mapped_column(
        chatbot_identity_enum, nullable=False,
        default=ChatbotIdentity.WEBSITE, server_default=text("'website'")
    )

    # ── Personality link ──────────────────────────────────────────────────────
    prompt_personality_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("prompt_personalities.id", ondelete="SET NULL"),
        nullable=True,
        comment="FK to prompt_personalities. NULL = use platform default (ARIA)."
    )

    # ── Tenant company profile (used to customise the static system prompt) ──
    company_profile: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"),
        comment=(
            "Tenant-specific branding injected into the system prompt. "
            "Keys: company_name, company_website, company_vision, "
            "company_description, tagline, contact_email, contact_phone, "
            "locations, portfolio_summary, industry."
        )
    )

    # ── Assembled prompt (static portion — personality + company profile) ─────
    system_prompt_template: Mapped[str | None] = mapped_column(
        Text, nullable=True, default=None,
        comment=(
            "Pre-rendered static system prompt. Regenerated whenever the chatbot "
            "config or company_profile is updated. Dynamic parts (RAG context, "
            "time awareness, returning-visitor recap) are appended at chat time."
        )
    )
    # ── Industry ──────────────────────────────────────────────────────────────
    industry: Mapped[str] = mapped_column(
        String(100), nullable=False,
        default="real_estate", server_default=text("'real_estate'"),
        comment="Slug matching industry_schemas.industry. Drives scraping, RAG, and insights."
    )

    custom_instructions: Mapped[str | None] = mapped_column(
        Text, nullable=True, default=None,
        comment=(
            "Tenant-supplied override instructions appended after the base "
            "personality in the system prompt."
        ),
    )
    model: Mapped[str | None] = mapped_column(
        String(64), nullable=True, default=None,
        comment=(
            "OpenAI chat model override for this chatbot. NULL = use platform default "
            "(settings.OPEN_AI_MODEL). Set to a premium model only if the tenant has "
            "the Premium AI add-on or is on a plan that includes it."
        ),
    )
    welcome_message: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    rag_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("FALSE"),
        comment="Flipped TRUE by worker after first DocumentChunk written. Never flip manually."
    )
    listing_filter_config: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"),
        comment=(
            "Generic listing filter applied during RAG search. Industry-specific. "
            "Examples: {'allowed_statuses': ['active']} or "
            "{'attribute_filters': {'listing_type': 'sale'}}."
        )
    )
    auto_close_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=15, server_default=text("15")
    )
    allowed_domains: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    branding: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"),
        comment=(
            "UI branding config + auto-populated asset URLs. "
            "Keys auto-set on asset upload: logo_url, avatar_url, banner_url, etc."
        )
    )
    lead_capture_config: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="chatbots", lazy="noload")
    prompt_personality: Mapped["PromptPersonality | None"] = relationship(
        "PromptPersonality", back_populates="chatbots", lazy="noload"
    )
    themes: Mapped[list["WidgetTheme"]] = relationship(
        "WidgetTheme", back_populates="chatbot_config",
        lazy="noload", cascade="all, delete-orphan"
    )
    knowledge_sources: Mapped[list["KnowledgeSource"]] = relationship(
        "KnowledgeSource", back_populates="chatbot_config",
        lazy="noload", cascade="all, delete-orphan"
    )
    campaigns: Mapped[list["Campaign"]] = relationship(
        "Campaign", back_populates="chatbot_config",
        lazy="noload", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_chatbot_configs_tenant", "tenant_id"),
        Index("ix_chatbot_configs_iframe_token", "iframe_token"),
        Index("ix_chatbot_configs_status", "tenant_id", "status"),
        Index("ix_chatbot_configs_personality", "prompt_personality_id"),
    )

    def __repr__(self) -> str:
        return f"<ChatbotConfig id={self.id} tenant={self.tenant_id} status={self.status}>"


# =============================================================================
# WIDGET THEMES
# =============================================================================

class WidgetTheme(Base, PublicIdMixin, TimestampMixin):
    __tablename__ = "widget_themes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    chatbot_config_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("chatbot_configs.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(
        String(100), nullable=False,
        default="Default Theme", server_default=text("'Default Theme'")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("FALSE"),
        comment="One TRUE per chatbot. Enforced by partial unique index. Swap in transaction."
    )
    is_paid_theme: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("FALSE")
    )
    colors: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    typography: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    assets: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    layout: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    chatbot_config: Mapped["ChatbotConfig"] = relationship(
        "ChatbotConfig", back_populates="themes", lazy="noload"
    )

    __table_args__ = (
        Index("ix_widget_themes_chatbot", "chatbot_config_id"),
        Index(
            "ix_widget_themes_one_active", "chatbot_config_id",
            unique=True, postgresql_where=text("is_active = TRUE")
        ),
    )

    def __repr__(self) -> str:
        return f"<WidgetTheme id={self.id} chatbot={self.chatbot_config_id} active={self.is_active}>"


# =============================================================================
# KNOWLEDGE SOURCES
# =============================================================================

class KnowledgeSource(Base, PublicIdMixin, TimestampMixin):
    __tablename__ = "knowledge_sources"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    chatbot_config_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("chatbot_configs.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[SourceType] = mapped_column(source_type_enum, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="active", server_default=text("'active'")
    )
    config: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    chatbot_config: Mapped["ChatbotConfig"] = relationship(
        "ChatbotConfig", back_populates="knowledge_sources", lazy="noload"
    )
    crawl_jobs: Mapped[list["CrawlJob"]] = relationship(
        "CrawlJob", back_populates="knowledge_source",
        lazy="noload", cascade="all, delete-orphan"
    )
    documents: Mapped[list["Document"]] = relationship(
        "Document", back_populates="knowledge_source",
        lazy="noload", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_knowledge_sources_tenant", "tenant_id"),
        Index("ix_knowledge_sources_chatbot", "chatbot_config_id"),
        Index("ix_knowledge_sources_type", "tenant_id", "type"),
    )

    def __repr__(self) -> str:
        return f"<KnowledgeSource id={self.id} type={self.type} chatbot={self.chatbot_config_id}>"


# =============================================================================
# CRAWL JOBS
# =============================================================================

class CrawlJob(Base, PublicIdMixin):
    __tablename__ = "crawl_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    knowledge_source_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("knowledge_sources.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False,
        comment="Denormalized for direct tenant-scoped queries."
    )
    base_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    status: Mapped[CrawlStatus] = mapped_column(
        crawl_status_enum, nullable=False,
        default=CrawlStatus.QUEUED, server_default=text("'queued'")
    )
    pages_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    pages_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    pages_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    triggered_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, default=None,
        comment="NULL = scheduled. Populated = manually triggered."
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )

    knowledge_source: Mapped["KnowledgeSource"] = relationship(
        "KnowledgeSource", back_populates="crawl_jobs", lazy="noload"
    )
    triggered_by_user: Mapped["User | None"] = relationship(
        "User", lazy="noload", foreign_keys=[triggered_by]
    )

    __table_args__ = (
        Index("ix_crawl_jobs_source", "knowledge_source_id"),
        Index("ix_crawl_jobs_tenant", "tenant_id"),
        Index(
            "ix_crawl_jobs_queued", "status", "created_at",
            postgresql_where=text("status IN ('queued', 'running')")
        ),
    )

    @property
    def is_finished(self) -> bool:
        return self.status in (CrawlStatus.COMPLETED, CrawlStatus.FAILED, CrawlStatus.CANCELLED)

    def __repr__(self) -> str:
        return f"<CrawlJob id={self.id} status={self.status} url={self.base_url!r}>"


# =============================================================================
# DOCUMENTS
# =============================================================================

class Document(Base, PublicIdMixin, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    knowledge_source_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("knowledge_sources.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False,
        comment="Denormalized — avoids joining knowledge_sources for tenant-scoped queries."
    )
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="'pdf' for now. 'docx', 'xlsx' in future."
    )
    file_size_bytes: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )

    # Blob now, S3 later
    file_data: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True, default=None,
        comment="Raw bytes. NULL after migrating to S3. Can clear after chunking."
    )
    storage_path: Mapped[str | None] = mapped_column(
        String(1000), nullable=True, default=None,
        comment="S3/GCS object key. NULL while using file_data."
    )

    status: Mapped[DocStatus] = mapped_column(
        doc_status_enum, nullable=False,
        default=DocStatus.UPLOADING, server_default=text("'uploading'")
    )
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    uploaded_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, default=None,
        comment="NULL for crawled pages. Populated for manual uploads."
    )

    knowledge_source: Mapped["KnowledgeSource"] = relationship(
        "KnowledgeSource", back_populates="documents", lazy="noload"
    )
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        "DocumentChunk", back_populates="document",
        lazy="noload", cascade="all, delete-orphan"
    )
    uploader: Mapped["User | None"] = relationship(
        "User", lazy="noload", foreign_keys=[uploaded_by]
    )

    __table_args__ = (
        Index("ix_documents_source", "knowledge_source_id"),
        Index("ix_documents_tenant", "tenant_id"),
        Index(
            "ix_documents_status", "status",
            postgresql_where=text("status IN ('uploading', 'processing')")
        ),
    )

    @property
    def is_ready(self) -> bool:
        return self.status == DocStatus.READY

    @property
    def using_blob_storage(self) -> bool:
        return self.file_data is not None and self.storage_path is None

    def __repr__(self) -> str:
        return f"<Document id={self.id} name={self.file_name!r} status={self.status}>"


# =============================================================================
# DOCUMENT CHUNKS
# =============================================================================

class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False,
        comment="Denormalized. Always include in RAG WHERE clause to prevent cross-tenant leakage."
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # pgvector embedding — HNSW index for O(log n) ANN queries
    embedding: Mapped[list[float]] = mapped_column(
        Vector(1536), nullable=True, default=None,
        comment="pgvector embedding. Tenant-scoped cosine search via HNSW index."
    )

    # PostgreSQL GENERATED tsvector for hybrid BM25-like full-text search.
    # Auto-populated from content by Postgres — never set manually.
    # Queried via plainto_tsquery / ts_rank_cd. GIN-indexed for fast lookup.
    ts_content = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', coalesce(content, ''))", persisted=True),
        nullable=True,
        comment="GENERATED tsvector for FTS. Auto-computed from content by Postgres.",
    )

    chunk_metadata: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"),
        comment='{"page": 3, "source_url": "...", "token_count": 312}'
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )

    document: Mapped["Document"] = relationship(
        "Document", back_populates="chunks", lazy="noload"
    )

    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_chunk_document_index"),
        Index("ix_chunks_document", "document_id"),
        Index("ix_chunks_tenant", "tenant_id"),
        # HNSW: O(log n) ANN, auto-updates on insert (no VACUUM needed unlike IVFFlat).
        # m=16 ef_construction=64 — good balance of recall vs build time.
        Index(
            "ix_chunks_embedding_hnsw", "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        # GIN index on tsvector for sub-millisecond full-text search.
        Index("ix_chunks_ts_content", "ts_content", postgresql_using="gin"),
    )

    def __repr__(self) -> str:
        return f"<DocumentChunk doc={self.document_id} idx={self.chunk_index} len={len(self.content)}>"


# =============================================================================
# LISTINGS
# =============================================================================

class Listing(Base, PublicIdMixin, SoftDeleteMixin):
    __tablename__ = "listings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[ListingSource] = mapped_column(
        listing_source_enum, nullable=False,
        default=ListingSource.MANUAL, server_default=text("'manual'")
    )
    external_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, default=None,
        comment="Dedup key for crawled listings. NULL for manual entries."
    )
    crawl_job_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("crawl_jobs.id", ondelete="SET NULL"),
        nullable=True, default=None
    )
    # ── Industry ──────────────────────────────────────────────────────────────
    industry: Mapped[str] = mapped_column(
        String(100), nullable=False,
        default="real_estate", server_default=text("'real_estate'"),
        comment="Matches chatbot_configs.industry. Tenant-scoped; never cross-query."
    )

    status: Mapped[str] = mapped_column(
        String(50), nullable=False,
        default="active", server_default=text("'active'"),
        comment="VARCHAR — any industry-defined status (active, sold, out_of_stock, …)."
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    price_display: Mapped[str | None] = mapped_column(String(100), nullable=True)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="USD", server_default=text("'USD'")
    )

    # ── Location (optional — restaurants, clinics, RE need it; e-commerce may not) ──
    street: Mapped[str | None] = mapped_column(String(255), nullable=True)
    suburb: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state: Mapped[str | None] = mapped_column(String(50), nullable=True)
    postcode: Mapped[str | None] = mapped_column(String(10), nullable=True)
    country: Mapped[str | None] = mapped_column(String(5), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    longitude: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)

    # ── Industry-specific fields (JSONB — no migration needed to add new industries) ──
    attributes: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"),
        comment=(
            "Industry-specific fields. Validated at app layer against IndustrySchema.attributes_schema. "
            "Examples — real_estate: {bedrooms, bathrooms, garages, listing_type, has_pool}; "
            "restaurant: {category, dietary_tags, spice_level}; "
            "ecommerce: {sku, brand, category, condition, stock_quantity}."
        )
    )

    media: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    raw_data: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    # Semantic embedding — built from title, description, location, and attributes.
    # Updated by embed_listing Celery task on create/update.
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(1536), nullable=True, default=None,
        comment="pgvector embedding for semantic listing search. HNSW-indexed."
    )

    listed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )

    tenant: Mapped["Tenant"] = relationship("Tenant", lazy="noload")
    crawl_job: Mapped["CrawlJob | None"] = relationship(
        "CrawlJob", lazy="noload", foreign_keys=[crawl_job_id]
    )

    __table_args__ = (
        # Primary access: all active listings for a tenant (list view)
        Index("ix_listings_tenant_status",
              "tenant_id", "status",
              postgresql_where=text("deleted_at IS NULL")),
        # Industry-scoped list (e.g. fetch only restaurant menu items for tenant)
        Index("ix_listings_tenant_industry",
              "tenant_id", "industry", "status",
              postgresql_where=text("deleted_at IS NULL")),
        # Location-based filtering (RE, restaurants, clinics, etc.)
        Index("ix_listings_suburb",
              "tenant_id", "suburb", "status",
              postgresql_where=text("deleted_at IS NULL")),
        # Price range filtering
        Index("ix_listings_price",
              "tenant_id", "price", "status",
              postgresql_where=text("deleted_at IS NULL")),
        # Dedup key for crawled / imported items
        Index("ix_listings_external", "tenant_id", "external_id",
              postgresql_where=text("external_id IS NOT NULL")),
        # GIN index on attributes JSONB — supports containment queries (@>)
        # e.g. WHERE attributes @> '{"listing_type": "sale"}'
        Index("ix_listings_attributes_gin", "attributes",
              postgresql_using="gin"),
        # HNSW for semantic fallback on listing search.
        Index(
            "ix_listings_embedding_hnsw", "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_where=text("deleted_at IS NULL AND embedding IS NOT NULL"),
        ),
    )

    def __repr__(self) -> str:
        return f"<Listing id={self.id} title={self.title!r} status={self.status}>"


# =============================================================================
# CHATBOT ASSETS  (images stored as blob — swap to S3 later)
# =============================================================================

class ChatbotAsset(Base, PublicIdMixin):
    __tablename__ = "chatbot_assets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    chatbot_config_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("chatbot_configs.id", ondelete="CASCADE"), nullable=False
    )
    # 'logo' | 'avatar' | 'banner' | 'gif' | 'ribbon_icon'
    asset_type: Mapped[str] = mapped_column(String(50), nullable=False)
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str] = mapped_column(
        String(100), nullable=False,
        comment="MIME type e.g. image/png — returned as Content-Type when serving."
    )
    file_size_bytes: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )
    # Raw bytes now; set storage_path + clear file_data when migrating to S3
    file_data: Mapped[bytes] = mapped_column(
        LargeBinary, nullable=False,
        comment="Raw image bytes. Clear after migrating to S3."
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )

    __table_args__ = (
        Index("ix_chatbot_assets_chatbot", "chatbot_config_id"),
        Index("ix_chatbot_assets_tenant", "tenant_id"),
    )

    def __repr__(self) -> str:
        return f"<ChatbotAsset id={self.id} type={self.asset_type} chatbot={self.chatbot_config_id}>"


# =============================================================================
# LISTING UPLOAD JOBS  (background file import tracking)
# =============================================================================

class ListingUploadJob(Base, TimestampMixin):
    __tablename__ = "listing_upload_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(
        String(36), nullable=False, unique=True,
        comment="External ID exposed in API responses."
    )
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    chatbot_config_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("chatbot_configs.id", ondelete="SET NULL"),
        nullable=True, default=None,
        comment="Which chatbot (and therefore which industry) this upload belongs to."
    )
    industry: Mapped[str] = mapped_column(
        String(100), nullable=False,
        default="real_estate", server_default=text("'real_estate'"),
        comment="Denormalized from chatbot_config.industry — available after chatbot is deleted."
    )
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(
        String(10), nullable=False, comment="'xlsx', 'xls', or 'csv'"
    )

    # Blob now, S3/GCS later
    file_data: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True, default=None,
        comment="Raw file bytes. NULL after migrating to S3."
    )
    storage_path: Mapped[str | None] = mapped_column(
        String(1000), nullable=True, default=None,
        comment="S3/GCS object key. NULL while using file_data."
    )

    status: Mapped[UploadJobStatus] = mapped_column(
        upload_job_status_enum, nullable=False,
        default=UploadJobStatus.QUEUED, server_default=text("'queued'")
    )
    total_rows: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    processed_rows: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)

    __table_args__ = (
        Index("ix_listing_upload_jobs_tenant", "tenant_id"),
        Index("ix_listing_upload_jobs_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<ListingUploadJob id={self.id} file={self.filename!r} status={self.status}>"