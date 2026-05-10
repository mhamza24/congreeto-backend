"""
app/modules/knowledge/repository.py

Pure DB access — no business logic. All methods are tenant-scoped.
Service layer is the only caller.
"""
from __future__ import annotations

import logging
from typing import List, Optional, Sequence

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.chatbot.models import (
    ChatbotAsset,
    ChatbotConfig,
    CrawlJob,
    Document,
    DocumentChunk,
    IndustrySchema,
    KnowledgeSource,
    Listing,
    ListingUploadJob,
    PromptPersonality,
    WidgetTheme,
)
from app.core.enums import CrawlStatus, DocStatus, ChatbotStatus, ListingStatus

logger = logging.getLogger(__name__)


# =============================================================================
# CHATBOT CONFIG
# =============================================================================

async def create_chatbot(
    db: AsyncSession,
    *,
    tenant_id: int,
    name: str,
    iframe_token: str,
    identity: str = "website",
    system_prompt_template: Optional[str] = None,
    welcome_message: Optional[str] = None,
    auto_close_minutes: int = 15,
    allowed_domains: list | None = None,
    branding: dict | None = None,
    lead_capture_config: dict | None = None,
    company_profile: dict | None = None,
    prompt_personality_id: Optional[int] = None,
    industry: str = "real_estate",
    listing_filter_config: dict | None = None,
    public_id: str,
) -> ChatbotConfig:
    chatbot = ChatbotConfig(
        tenant_id=tenant_id,
        name=name,
        iframe_token=iframe_token,
        identity=identity,
        system_prompt_template=system_prompt_template,
        welcome_message=welcome_message,
        auto_close_minutes=auto_close_minutes,
        allowed_domains=allowed_domains or [],
        branding=branding or {},
        lead_capture_config=lead_capture_config or {},
        company_profile=company_profile or {},
        prompt_personality_id=prompt_personality_id,
        industry=industry,
        listing_filter_config=listing_filter_config or {},
        public_id=public_id,
    )
    db.add(chatbot)
    await db.flush()
    return chatbot


async def get_chatbot_by_id(
    db: AsyncSession, *, tenant_id: int, chatbot_id: int
) -> Optional[ChatbotConfig]:
    result = await db.execute(
        select(ChatbotConfig).where(
            ChatbotConfig.id == chatbot_id,
            ChatbotConfig.tenant_id == tenant_id,
        )
    )
    return result.scalar_one_or_none()


async def get_chatbot_by_public_id(
    db: AsyncSession, *, tenant_id: int, public_id: str
) -> Optional[ChatbotConfig]:
    result = await db.execute(
        select(ChatbotConfig).where(
            ChatbotConfig.public_id == public_id,
            ChatbotConfig.tenant_id == tenant_id,
        )
    )
    return result.scalar_one_or_none()


async def get_chatbot_by_iframe_token(
    db: AsyncSession, *, iframe_token: str
) -> Optional[ChatbotConfig]:
    """Used by the widget embed — no tenant_id needed (token is globally unique)."""
    result = await db.execute(
        select(ChatbotConfig).where(ChatbotConfig.iframe_token == iframe_token)
    )
    return result.scalar_one_or_none()


# =============================================================================
# PROMPT PERSONALITIES
# =============================================================================

async def get_prompt_personality_by_slug(
    db: AsyncSession, *, slug: str
) -> Optional[PromptPersonality]:
    result = await db.execute(
        select(PromptPersonality).where(
            PromptPersonality.slug == slug,
            PromptPersonality.is_active == True,
        )
    )
    return result.scalar_one_or_none()


async def get_prompt_personality_by_id(
    db: AsyncSession, *, personality_id: int
) -> Optional[PromptPersonality]:
    result = await db.execute(
        select(PromptPersonality).where(PromptPersonality.id == personality_id)
    )
    return result.scalar_one_or_none()


async def list_prompt_personalities(db: AsyncSession) -> Sequence[PromptPersonality]:
    result = await db.execute(
        select(PromptPersonality)
        .where(PromptPersonality.is_active == True)
        .order_by(PromptPersonality.name)
    )
    return result.scalars().all()


# =============================================================================
# INDUSTRY SCHEMA
# =============================================================================

async def get_industry_schema(
    db: AsyncSession, *, industry: str
) -> Optional[IndustrySchema]:
    """Return the IndustrySchema row for the given industry slug, or None."""
    result = await db.execute(
        select(IndustrySchema).where(
            IndustrySchema.industry == industry,
            IndustrySchema.is_active == True,
        )
    )
    return result.scalar_one_or_none()


# =============================================================================
# CHATBOT BRANDING ASSET URL UPDATE
# =============================================================================

# Maps asset_type → the branding JSONB key that holds its URL
_ASSET_TYPE_TO_BRANDING_KEY: dict[str, str] = {
    "logo":        "logo_url",
    "avatar":      "avatar_url",
    "banner":      "banner_url",
    "gif":         "gif_url",
    "ribbon_icon": "ribbon_icon_url",
}


async def update_chatbot_branding_asset_url(
    db: AsyncSession,
    *,
    chatbot_config_id: int,
    asset_type: str,
    asset_url: str,
) -> None:
    """
    Merge the asset URL into ChatbotConfig.branding JSONB under the appropriate key.
    Uses PostgreSQL's || operator for a single-round-trip atomic update.
    """
    branding_key = _ASSET_TYPE_TO_BRANDING_KEY.get(asset_type)
    if not branding_key:
        return  # unknown asset type — skip, don't corrupt branding

    await db.execute(
        update(ChatbotConfig)
        .where(ChatbotConfig.id == chatbot_config_id)
        .values(
            branding=ChatbotConfig.branding.op("||")(
                func.jsonb_build_object(branding_key, asset_url)
            )
        )
    )


async def list_chatbots(
    db: AsyncSession, *, tenant_id: int, status: Optional[str] = None
) -> Sequence[ChatbotConfig]:
    q = select(ChatbotConfig).where(ChatbotConfig.tenant_id == tenant_id)
    if status:
        q = q.where(ChatbotConfig.status == status)
    result = await db.execute(q.order_by(ChatbotConfig.created_at.desc()))
    return result.scalars().all()


async def update_chatbot(
    db: AsyncSession, *, chatbot: ChatbotConfig, **kwargs
) -> ChatbotConfig:
    for key, value in kwargs.items():
        setattr(chatbot, key, value)
    await db.flush()
    return chatbot


async def flip_rag_enabled(
    db: AsyncSession, *, tenant_id: int, chatbot_id: int
) -> None:
    """
    Flip rag_enabled=True only if at least one DocumentChunk exists
    for this chatbot. Called by the chunk-writer worker after each commit.
    """
    chunks_exist = await db.execute(
        select(
            exists().where(
                and_(
                    DocumentChunk.tenant_id == tenant_id,
                    Document.id == DocumentChunk.document_id,
                    KnowledgeSource.id == Document.knowledge_source_id,
                    KnowledgeSource.chatbot_config_id == chatbot_id,
                )
            )
        )
    )
    if chunks_exist.scalar():
        await db.execute(
            update(ChatbotConfig)
            .where(
                ChatbotConfig.id == chatbot_id,
                ChatbotConfig.tenant_id == tenant_id,
            )
            .values(rag_enabled=True)
        )


async def chatbot_has_ready_knowledge(
    db: AsyncSession, *, tenant_id: int, chatbot_id: int
) -> bool:
    """
    Service layer check before allowing status → 'active'.
    At least one of:
      - knowledge_source(website) with ≥1 completed crawl_job
      - knowledge_source(document) with ≥1 ready document
    """
    website_ready = await db.execute(
        select(
            exists().where(
                and_(
                    KnowledgeSource.chatbot_config_id == chatbot_id,
                    KnowledgeSource.tenant_id == tenant_id,
                    KnowledgeSource.type == "website",
                    CrawlJob.knowledge_source_id == KnowledgeSource.id,
                    CrawlJob.status == CrawlStatus.COMPLETED,
                )
            )
        )
    )
    if website_ready.scalar():
        return True

    doc_ready = await db.execute(
        select(
            exists().where(
                and_(
                    KnowledgeSource.chatbot_config_id == chatbot_id,
                    KnowledgeSource.tenant_id == tenant_id,
                    KnowledgeSource.type.in_(["document", "manual_qa"]),
                    Document.knowledge_source_id == KnowledgeSource.id,
                    Document.status == DocStatus.READY,
                )
            )
        )
    )
    return bool(doc_ready.scalar())


# =============================================================================
# WIDGET THEME
# =============================================================================

async def create_widget_theme(
    db: AsyncSession,
    *,
    tenant_id: int,
    chatbot_config_id: int,
    name: str = "Default Theme",
    is_active: bool = True,
    is_paid_theme: bool = False,
    public_id: str,
    colors: dict | None = None,
    typography: dict | None = None,
    assets: dict | None = None,
    layout: dict | None = None,
) -> WidgetTheme:
    theme = WidgetTheme(
        tenant_id=tenant_id,
        chatbot_config_id=chatbot_config_id,
        name=name,
        is_active=is_active,
        is_paid_theme=is_paid_theme,
        public_id=public_id,
        colors=colors or {},
        typography=typography or {},
        assets=assets or {},
        layout=layout or {},
    )
    db.add(theme)
    await db.flush()
    return theme


async def get_active_theme(
    db: AsyncSession, *, chatbot_config_id: int
) -> Optional[WidgetTheme]:
    result = await db.execute(
        select(WidgetTheme).where(
            WidgetTheme.chatbot_config_id == chatbot_config_id,
            WidgetTheme.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def list_themes(
    db: AsyncSession, *, chatbot_config_id: int
) -> Sequence[WidgetTheme]:
    result = await db.execute(
        select(WidgetTheme)
        .where(WidgetTheme.chatbot_config_id == chatbot_config_id)
        .order_by(WidgetTheme.created_at.desc())
    )
    return result.scalars().all()


# =============================================================================
# KNOWLEDGE SOURCE
# =============================================================================

async def create_knowledge_source(
    db: AsyncSession,
    *,
    tenant_id: int,
    chatbot_config_id: int,
    type: str,
    name: str,
    config: dict | None = None,
    public_id: str,
) -> KnowledgeSource:
    source = KnowledgeSource(
        tenant_id=tenant_id,
        chatbot_config_id=chatbot_config_id,
        type=type,
        name=name,
        config=config or {},
        public_id=public_id,
    )
    db.add(source)
    await db.flush()
    return source


async def get_knowledge_source(
    db: AsyncSession, *, tenant_id: int, source_id: int
) -> Optional[KnowledgeSource]:
    result = await db.execute(
        select(KnowledgeSource).where(
            KnowledgeSource.id == source_id,
            KnowledgeSource.tenant_id == tenant_id,
        )
    )
    return result.scalar_one_or_none()


async def get_knowledge_source_by_public_id(
    db: AsyncSession, *, tenant_id: int, public_id: str
) -> Optional[KnowledgeSource]:
    result = await db.execute(
        select(KnowledgeSource).where(
            KnowledgeSource.public_id == public_id,
            KnowledgeSource.tenant_id == tenant_id,
        )
    )
    return result.scalar_one_or_none()


async def update_knowledge_source(
    db: AsyncSession,
    *,
    source: KnowledgeSource,
    type: Optional[str] = None,
    name: Optional[str] = None,
    config: Optional[dict] = None,
) -> KnowledgeSource:
    if type is not None:
        source.type = type
    if name is not None:
        source.name = name
    if config is not None:
        source.config = config
    await db.commit()
    await db.refresh(source)
    return source


async def delete_knowledge_source(
    db: AsyncSession, *, source: KnowledgeSource
) -> None:
    await db.delete(source)
    await db.commit()


async def list_knowledge_sources(
    db: AsyncSession, *, tenant_id: int, chatbot_config_id: int
) -> Sequence[KnowledgeSource]:
    result = await db.execute(
        select(KnowledgeSource).where(
            KnowledgeSource.tenant_id == tenant_id,
            KnowledgeSource.chatbot_config_id == chatbot_config_id,
        )
    )
    return result.scalars().all()


# =============================================================================
# CRAWL JOB
# =============================================================================

async def create_crawl_job(
    db: AsyncSession,
    *,
    knowledge_source_id: int,
    tenant_id: int,
    base_url: str,
    triggered_by: Optional[int] = None,
    public_id: str,
) -> CrawlJob:
    job = CrawlJob(
        knowledge_source_id=knowledge_source_id,
        tenant_id=tenant_id,
        base_url=base_url,
        triggered_by=triggered_by,
        public_id=public_id,
    )
    db.add(job)
    await db.flush()
    return job


async def get_crawl_job(
    db: AsyncSession, *, tenant_id: int, job_id: int
) -> Optional[CrawlJob]:
    result = await db.execute(
        select(CrawlJob).where(
            CrawlJob.id == job_id,
            CrawlJob.tenant_id == tenant_id,
        )
    )
    return result.scalar_one_or_none()


async def get_crawl_job_by_public_id(
    db: AsyncSession, *, tenant_id: int, public_id: str
) -> Optional[CrawlJob]:
    result = await db.execute(
        select(CrawlJob).where(
            CrawlJob.public_id == public_id,
            CrawlJob.tenant_id == tenant_id,
        )
    )
    return result.scalar_one_or_none()


async def list_crawl_jobs(
    db: AsyncSession, *, tenant_id: int, knowledge_source_id: int
) -> Sequence[CrawlJob]:
    result = await db.execute(
        select(CrawlJob).where(
            CrawlJob.tenant_id == tenant_id,
            CrawlJob.knowledge_source_id == knowledge_source_id,
        ).order_by(CrawlJob.created_at.desc())
    )
    return result.scalars().all()


async def get_stuck_crawl_jobs(
    db: AsyncSession,
    *,
    queued_older_than_minutes: int = 5,
    running_older_than_minutes: int = 30,
) -> Sequence[CrawlJob]:
    """
    Returns crawl jobs that are stuck and need to be re-queued:
      - status=queued  and created_at older than queued_older_than_minutes
      - status=running and started_at older than running_older_than_minutes
    Eagerly loads knowledge_source so the caller can read chatbot_config_id.
    """
    from sqlalchemy.orm import joinedload
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(CrawlJob)
        .options(joinedload(CrawlJob.knowledge_source))
        .where(
            and_(
                CrawlJob.status.in_([CrawlStatus.QUEUED, CrawlStatus.RUNNING]),
            )
        )
        .where(
            (
                (CrawlJob.status == CrawlStatus.QUEUED) &
                (CrawlJob.created_at < now - timedelta(minutes=queued_older_than_minutes))
            ) | (
                (CrawlJob.status == CrawlStatus.RUNNING) &
                (CrawlJob.started_at < now - timedelta(minutes=running_older_than_minutes))
            )
        )
    )
    return result.scalars().all()


async def update_crawl_job(
    db: AsyncSession, *, job: CrawlJob, **kwargs
) -> CrawlJob:
    for key, value in kwargs.items():
        setattr(job, key, value)
    await db.flush()
    return job


async def atomic_increment_crawl_page(
    db: AsyncSession,
    *,
    job_id: int,
    success: bool,
) -> tuple[int, int, int]:
    """
    Atomically increment pages_processed (success=True) or pages_failed (success=False).

    Uses UPDATE ... RETURNING so the caller gets a consistent post-update view
    without a second SELECT.  This is safe under concurrent per-page workers.

    Returns:
        (pages_processed, pages_failed, pages_found) after the update.
        Returns (0, 0, 0) if the job row no longer exists.
    """
    if success:
        stmt = (
            update(CrawlJob)
            .where(CrawlJob.id == job_id)
            .values(pages_processed=CrawlJob.pages_processed + 1)
            .returning(
                CrawlJob.pages_processed,
                CrawlJob.pages_failed,
                CrawlJob.pages_found,
            )
        )
    else:
        stmt = (
            update(CrawlJob)
            .where(CrawlJob.id == job_id)
            .values(pages_failed=CrawlJob.pages_failed + 1)
            .returning(
                CrawlJob.pages_processed,
                CrawlJob.pages_failed,
                CrawlJob.pages_found,
            )
        )
    result = await db.execute(stmt)
    row = result.fetchone()
    if row is None:
        return 0, 0, 0
    return int(row[0]), int(row[1]), int(row[2])


# =============================================================================
# DOCUMENT
# =============================================================================

async def create_document(
    db: AsyncSession,
    *,
    knowledge_source_id: int,
    tenant_id: int,
    file_name: str,
    file_type: str,
    file_size_bytes: int = 0,
    file_data: Optional[bytes] = None,
    storage_path: Optional[str] = None,
    uploaded_by: Optional[int] = None,
    public_id: str,
) -> Document:
    doc = Document(
        knowledge_source_id=knowledge_source_id,
        tenant_id=tenant_id,
        file_name=file_name,
        file_type=file_type,
        file_size_bytes=file_size_bytes,
        file_data=file_data,
        storage_path=storage_path,
        uploaded_by=uploaded_by,
        public_id=public_id,
    )
    db.add(doc)
    await db.flush()
    return doc


async def get_document(
    db: AsyncSession, *, tenant_id: int, document_id: int
) -> Optional[Document]:
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.tenant_id == tenant_id,
        )
    )
    return result.scalar_one_or_none()


async def get_document_by_public_id(
    db: AsyncSession, *, tenant_id: int, public_id: str
) -> Optional[Document]:
    result = await db.execute(
        select(Document).where(
            Document.public_id == public_id,
            Document.tenant_id == tenant_id,
        )
    )
    return result.scalar_one_or_none()


async def list_documents(
    db: AsyncSession,
    *,
    tenant_id: int,
    knowledge_source_id: int,
    status: Optional[str] = None,
) -> Sequence[Document]:
    q = select(Document).where(
        Document.tenant_id == tenant_id,
        Document.knowledge_source_id == knowledge_source_id,
    )
    if status:
        q = q.where(Document.status == status)
    result = await db.execute(q.order_by(Document.created_at.desc()))
    return result.scalars().all()


async def update_document(
    db: AsyncSession, *, doc: Document, **kwargs
) -> Document:
    for key, value in kwargs.items():
        setattr(doc, key, value)
    await db.flush()
    return doc


async def get_stale_documents(
    db: AsyncSession,
    *,
    failed_or_processing_older_than_minutes: int = 10,
) -> Sequence[Document]:
    """
    Return documents stuck in FAILED or PROCESSING state for longer than
    the given threshold.

    PROCESSING documents older than the threshold are treated as orphaned —
    the Celery worker processing them likely crashed before finishing.
    FAILED documents are candidates for automatic retry.

    Eagerly loads knowledge_source so callers can read chatbot_config_id.
    """
    from sqlalchemy.orm import joinedload

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=failed_or_processing_older_than_minutes)
    result = await db.execute(
        select(Document)
        .options(joinedload(Document.knowledge_source))
        .where(
            Document.status.in_([DocStatus.FAILED, DocStatus.PROCESSING]),
            Document.created_at < cutoff,
        )
        .order_by(Document.created_at)
        .limit(50)  # cap per run to avoid thundering herd on startup
    )
    return result.scalars().all()


# =============================================================================
# DOCUMENT CHUNKS
# =============================================================================

async def bulk_create_chunks(
    db: AsyncSession,
    *,
    chunks: List[DocumentChunk],
) -> None:
    """Insert all chunks for a document in one flush."""
    db.add_all(chunks)
    await db.flush()


async def get_chunks_for_document(
    db: AsyncSession, *, document_id: int
) -> Sequence[DocumentChunk]:
    result = await db.execute(
        select(DocumentChunk)
        .where(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index)
    )
    return result.scalars().all()


async def delete_chunks_for_document(
    db: AsyncSession, *, document_id: int
) -> None:
    """Used when re-processing a document."""
    chunks = await get_chunks_for_document(db, document_id=document_id)
    for chunk in chunks:
        await db.delete(chunk)
    await db.flush()


async def get_crawled_urls_for_source(
    db: AsyncSession,
    *,
    knowledge_source_id: int,
    tenant_id: int,
) -> set[str]:
    """
    Return URLs already successfully crawled for a knowledge source.
    Used by incremental re-crawl to skip pages already in the knowledge base.
    Only includes READY documents (PROCESSING/FAILED are treated as not done).
    """
    result = await db.execute(
        select(Document.file_name).where(
            Document.knowledge_source_id == knowledge_source_id,
            Document.tenant_id == tenant_id,
            Document.file_type == "html",
            Document.status == DocStatus.READY,
        )
    )
    return {row[0] for row in result.all()}


async def update_widget_theme(
    db: AsyncSession, *, theme: WidgetTheme, **kwargs
) -> WidgetTheme:
    for key, value in kwargs.items():
        setattr(theme, key, value)
    await db.flush()
    return theme


async def get_theme_by_public_id(
    db: AsyncSession, *, chatbot_config_id: int, public_id: str
) -> Optional[WidgetTheme]:
    result = await db.execute(
        select(WidgetTheme).where(
            WidgetTheme.public_id == public_id,
            WidgetTheme.chatbot_config_id == chatbot_config_id,
        )
    )
    return result.scalar_one_or_none()


async def deactivate_all_themes(
    db: AsyncSession, *, chatbot_config_id: int
) -> None:
    """Set is_active=False on all themes for this chatbot before activating another."""
    themes = await list_themes(db, chatbot_config_id=chatbot_config_id)
    for t in themes:
        t.is_active = False
    await db.flush()


# =============================================================================
# PLAN LIMIT HELPERS
# =============================================================================

async def count_chatbots_for_tenant(
    db: AsyncSession, *, tenant_id: int
) -> int:
    result = await db.execute(
        select(func.count()).select_from(ChatbotConfig).where(
            ChatbotConfig.tenant_id == tenant_id,
        )
    )
    return result.scalar_one()


async def admin_list_all_chatbots(
    db: AsyncSession,
) -> list[ChatbotConfig]:
    result = await db.execute(select(ChatbotConfig).order_by(ChatbotConfig.id.desc()))
    return list(result.scalars().all())


async def admin_set_chatbot_status(
    db: AsyncSession, *, public_id: str, new_status: str
) -> Optional[ChatbotConfig]:
    result = await db.execute(select(ChatbotConfig).where(ChatbotConfig.public_id == public_id))
    chatbot = result.scalar_one_or_none()
    if not chatbot:
        return None
    chatbot.status = new_status
    await db.commit()
    await db.refresh(chatbot)
    return chatbot


async def admin_delete_chatbot(
    db: AsyncSession, *, public_id: str
) -> bool:
    result = await db.execute(select(ChatbotConfig).where(ChatbotConfig.public_id == public_id))
    chatbot = result.scalar_one_or_none()
    if not chatbot:
        return False
    await db.delete(chatbot)
    await db.commit()
    return True


async def count_documents_for_tenant(
    db: AsyncSession, *, tenant_id: int
) -> int:
    """Count all non-failed documents for this tenant (for max_documents gate)."""
    result = await db.execute(
        select(func.count()).select_from(Document).where(
            Document.tenant_id == tenant_id,
            Document.status != DocStatus.FAILED,
        )
    )
    return result.scalar_one()


async def count_storage_bytes_for_tenant(
    db: AsyncSession, *, tenant_id: int
) -> int:
    """Sum file_size_bytes across all non-failed docs (for max_storage_mb gate)."""
    result = await db.execute(
        select(func.coalesce(func.sum(Document.file_size_bytes), 0)).where(
            Document.tenant_id == tenant_id,
            Document.status != DocStatus.FAILED,
        )
    )
    return result.scalar_one()


# =============================================================================
# CHATBOT ASSETS  (blob images)
# =============================================================================

async def create_asset(
    db: AsyncSession,
    *,
    tenant_id: int,
    chatbot_config_id: int,
    asset_type: str,
    file_name: str,
    content_type: str,
    file_size_bytes: int,
    file_data: bytes,
    public_id: str,
) -> ChatbotAsset:
    asset = ChatbotAsset(
        tenant_id=tenant_id,
        chatbot_config_id=chatbot_config_id,
        asset_type=asset_type,
        file_name=file_name,
        content_type=content_type,
        file_size_bytes=file_size_bytes,
        file_data=file_data,
        public_id=public_id,
    )
    db.add(asset)
    await db.flush()
    return asset


async def get_asset_by_public_id(
    db: AsyncSession, *, public_id: str
) -> Optional[ChatbotAsset]:
    """No tenant scope here — public_id is the access token for widget rendering."""
    result = await db.execute(
        select(ChatbotAsset).where(ChatbotAsset.public_id == public_id)
    )
    return result.scalar_one_or_none()


# =============================================================================
# HYBRID SEARCH  (vector cosine + full-text, merged with RRF)
# =============================================================================

# Candidates fetched per source before RRF merge.
# Over-fetching improves recall — RRF trims to top_k after merge.
_CANDIDATE_K = 20
# RRF constant (k=60 is the standard recommendation from the literature).
_RRF_K = 60


def _rrf_merge(
    vector_chunks: Sequence[DocumentChunk],
    fts_chunks: Sequence[DocumentChunk],
    top_k: int,
) -> List[DocumentChunk]:
    """
    Reciprocal Rank Fusion: score(d) = Σ 1/(k + rank_i(d)).
    Merges two ranked lists by position only (ignores raw scores).
    O(n) — negligible latency overhead.
    """
    scores: dict[int, float] = {}
    id_to_chunk: dict[int, DocumentChunk] = {}

    for rank, chunk in enumerate(vector_chunks, start=1):
        scores[chunk.id] = scores.get(chunk.id, 0.0) + 1.0 / (_RRF_K + rank)
        id_to_chunk[chunk.id] = chunk

    for rank, chunk in enumerate(fts_chunks, start=1):
        scores[chunk.id] = scores.get(chunk.id, 0.0) + 1.0 / (_RRF_K + rank)
        id_to_chunk[chunk.id] = chunk

    sorted_ids = sorted(scores, key=lambda cid: scores[cid], reverse=True)
    return [id_to_chunk[cid] for cid in sorted_ids[:top_k]]


async def hybrid_search(
    db: AsyncSession,
    *,
    tenant_id: int,
    chatbot_config_id: int,
    query_embedding: List[float],
    query_text: str,
    top_k: int = 8,
) -> List[DocumentChunk]:
    """
    Hybrid retrieval: dense vector (HNSW cosine) + sparse FTS (tsvector ts_rank_cd).
    Results merged with Reciprocal Rank Fusion (RRF, k=60).

    Always scoped to (tenant_id, chatbot_config_id) — no cross-tenant leakage.
    Returns at most top_k chunks ordered by combined RRF score.
    """
    _scope = and_(
        DocumentChunk.tenant_id == tenant_id,
        KnowledgeSource.chatbot_config_id == chatbot_config_id,
    )
    _joins = (
        select(DocumentChunk)
        .join(Document, Document.id == DocumentChunk.document_id)
        .join(KnowledgeSource, KnowledgeSource.id == Document.knowledge_source_id)
    )

    # ── Leg 1: dense vector search (HNSW cosine) ─────────────────────────────
    vec_q = (
        _joins.where(_scope, DocumentChunk.embedding.isnot(None))
        .order_by(DocumentChunk.embedding.cosine_distance(query_embedding))
        .limit(_CANDIDATE_K)
    )
    vec_result = await db.execute(vec_q)
    vector_chunks: Sequence[DocumentChunk] = vec_result.scalars().all()

    # ── Leg 2: full-text search (tsvector / ts_rank_cd) ───────────────────────
    tsquery = func.plainto_tsquery("english", query_text)
    fts_q = (
        _joins.where(
            _scope,
            DocumentChunk.ts_content.op("@@")(tsquery),
        )
        .order_by(
            func.ts_rank_cd(DocumentChunk.ts_content, tsquery).desc()
        )
        .limit(_CANDIDATE_K)
    )
    try:
        fts_result = await db.execute(fts_q)
        fts_chunks: Sequence[DocumentChunk] = fts_result.scalars().all()
    except Exception:
        # ts_content column may not exist yet (pre-migration). Degrade gracefully.
        fts_chunks = []

    # ── RRF merge ─────────────────────────────────────────────────────────────
    return _rrf_merge(vector_chunks, fts_chunks, top_k)


# =============================================================================
# LISTING SIMILARITY SEARCH
# =============================================================================

async def get_listing_by_public_id(
    db: AsyncSession, *, tenant_id: int, public_id: str
) -> Optional[Listing]:
    result = await db.execute(
        select(Listing).where(
            Listing.public_id == public_id,
            Listing.tenant_id == tenant_id,
            Listing.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def list_listings(
    db: AsyncSession,
    *,
    tenant_id: int,
    suburb: Optional[str] = None,
    industry: Optional[str] = None,
    status_filter: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Sequence[Listing]:
    q = select(Listing).where(
        Listing.tenant_id == tenant_id,
        Listing.deleted_at.is_(None),
    )
    if suburb:
        q = q.where(Listing.suburb.ilike(f"%{suburb}%"))
    if industry:
        q = q.where(Listing.industry == industry)
    if status_filter:
        q = q.where(Listing.status == status_filter)
    q = q.order_by(Listing.updated_at.desc()).limit(limit).offset(offset)
    result = await db.execute(q)
    return result.scalars().all()


async def count_active_listings(
    db: AsyncSession,
    *,
    tenant_id: int,
    industry: Optional[str] = None,
) -> int:
    """Total active, non-deleted listings for a tenant."""
    q = select(func.count(Listing.id)).where(
        Listing.tenant_id == tenant_id,
        Listing.deleted_at.is_(None),
        Listing.status == ListingStatus.ACTIVE,
    )
    if industry:
        q = q.where(Listing.industry == industry)
    result = await db.execute(q)
    return result.scalar_one()


async def listing_similarity_search(
    db: AsyncSession,
    *,
    tenant_id: int,
    query_embedding: List[float],
    top_k: int = 5,
    industry: Optional[str] = None,
    attribute_filters: Optional[dict] = None,
) -> Sequence[Listing]:
    """
    Semantic search on the listings table.
    Only returns ACTIVE, non-deleted listings.

    Falls back to the most-recent active listings when none have embeddings yet
    (e.g. Celery worker hasn't run, or embed_listing task is still pending).
    """
    _active_filters = [
        Listing.tenant_id == tenant_id,
        Listing.deleted_at.is_(None),
        Listing.status == ListingStatus.ACTIVE,
    ]
    if industry:
        _active_filters.append(Listing.industry == industry)
    if attribute_filters:
        _active_filters.append(Listing.attributes.contains(attribute_filters))

    _active_scope = tuple(_active_filters)

    # ── Primary: vector similarity search (requires embedding) ────────────────
    vec_result = await db.execute(
        select(Listing)
        .where(*_active_scope, Listing.embedding.isnot(None))
        .order_by(Listing.embedding.cosine_distance(query_embedding))
        .limit(top_k)
    )
    listings = list(vec_result.scalars().all())

    logger.debug("[rag] listing_similarity_search vector returned %d listings tenant=%d", len(listings), tenant_id)

    # ── Fallback: no embeddings exist yet → return most-recent active listings ─
    if not listings:
        fallback_result = await db.execute(
            select(Listing)
            .where(*_active_scope)
            .order_by(Listing.updated_at.desc())
            .limit(top_k)
        )
        listings = list(fallback_result.scalars().all())
        logger.info(
            "[rag] listing_similarity_search fallback used — returned %d most-recent listings. "
            "Run embed_listing to enable semantic ranking. tenant=%d",
            len(listings), tenant_id,
        )

    for lst in listings:
        logger.debug(
            "[rag]   listing id=%d public_id=%s title=%r status=%s embedding=%s",
            lst.id, lst.public_id, lst.title, lst.status,
            "set" if lst.embedding is not None else "NULL",
        )

    return listings


async def update_listing_embedding(
    db: AsyncSession,
    *,
    tenant_id: int,
    listing_id: int,
    embedding: List[float],
) -> None:
    """Set or refresh the embedding for a listing row."""
    await db.execute(
        update(Listing)
        .where(Listing.id == listing_id, Listing.tenant_id == tenant_id)
        .values(embedding=embedding)
    )


async def clear_listing_embedding(
    db: AsyncSession,
    *,
    tenant_id: int,
    listing_id: int,
) -> None:
    """
    NULL-out the embedding when a listing is soft-deleted or archived.
    Frees pgvector HNSW index slot and excludes the row from ANN scans.
    """
    await db.execute(
        update(Listing)
        .where(Listing.id == listing_id, Listing.tenant_id == tenant_id)
        .values(embedding=None)
    )


async def get_listing_by_id(
    db: AsyncSession, *, tenant_id: int, listing_id: int
) -> Optional[Listing]:
    result = await db.execute(
        select(Listing).where(
            Listing.id == listing_id,
            Listing.tenant_id == tenant_id,
            Listing.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def get_listings_by_ids(
    db: AsyncSession,
    *,
    tenant_id: int,
    listing_ids: List[int],
) -> List[Listing]:
    """Fetch multiple listings by primary key in ONE query."""
    if not listing_ids:
        return []
    result = await db.execute(
        select(Listing).where(
            Listing.tenant_id == tenant_id,
            Listing.id.in_(listing_ids),
            Listing.deleted_at.is_(None),
        )
    )
    return list(result.scalars().all())


async def bulk_update_listing_embeddings(
    db: AsyncSession,
    *,
    tenant_id: int,
    id_to_embedding: dict,
) -> None:
    """Update embeddings for multiple listings in a single round-trip using bulk mappings."""
    if not id_to_embedding:
        return
    await db.execute(
        update(Listing),
        [
            {"id": listing_id, "tenant_id": tenant_id, "embedding": emb}
            for listing_id, emb in id_to_embedding.items()
        ],
    )


# =============================================================================
# LISTING CRUD
# =============================================================================

async def create_listing(
    db: AsyncSession,
    *,
    tenant_id: int,
    crawl_job_id: Optional[int] = None,
    source: str,
    external_id: Optional[str] = None,
    industry: str = "real_estate",
    title: str,
    status: str = "active",
    description: Optional[str] = None,
    price: Optional[float] = None,
    price_display: Optional[str] = None,
    currency: str = "AUD",
    street: Optional[str] = None,
    suburb: Optional[str] = None,
    state: Optional[str] = None,
    postcode: Optional[str] = None,
    country: str = "AU",
    attributes: Optional[dict] = None,
    media: Optional[list] = None,
    raw_data: Optional[dict] = None,
    public_id: str = "",
) -> Listing:
    listing = Listing(
        tenant_id=tenant_id,
        crawl_job_id=crawl_job_id,
        source=source,
        external_id=external_id,
        industry=industry,
        title=title,
        status=status,
        description=description,
        price=price,
        price_display=price_display,
        currency=currency,
        street=street,
        suburb=suburb,
        state=state,
        postcode=postcode,
        country=country,
        attributes=attributes or {},
        media=media or [],
        raw_data=raw_data or {},
        public_id=public_id,
    )
    db.add(listing)
    await db.flush()
    return listing


async def get_listing_by_external_id(
    db: AsyncSession, *, tenant_id: int, external_id: str
) -> Optional[Listing]:
    result = await db.execute(
        select(Listing).where(
            Listing.tenant_id == tenant_id,
            Listing.external_id == external_id,
            Listing.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def get_listings_by_external_ids(
    db: AsyncSession,
    *,
    tenant_id: int,
    external_ids: List[str],
) -> dict[str, Listing]:
    """
    Fetch multiple listings by external_id in ONE query.
    Returns a dict keyed by external_id for O(1) lookup.
    Used by batch-import tasks to avoid N+1 existence checks.
    """
    if not external_ids:
        return {}
    result = await db.execute(
        select(Listing).where(
            Listing.tenant_id == tenant_id,
            Listing.external_id.in_(external_ids),
            Listing.deleted_at.is_(None),
        )
    )
    return {lst.external_id: lst for lst in result.scalars().all()}


async def upsert_listing(
    db: AsyncSession,
    *,
    tenant_id: int,
    external_id: str,
    **fields,
) -> tuple[Listing, bool]:
    """
    Insert if external_id is new, otherwise update existing row.
    Returns (listing, created: bool).
    """
    existing = await get_listing_by_external_id(
        db, tenant_id=tenant_id, external_id=external_id
    )
    if existing:
        for key, value in fields.items():
            if value is not None:
                setattr(existing, key, value)
        await db.flush()
        return existing, False

    listing = await create_listing(
        db, tenant_id=tenant_id, external_id=external_id, **fields
    )
    return listing, True


# =============================================================================
# DOCUMENT BYTES  (for download endpoint — fetched separately to avoid OOM)
# =============================================================================

async def get_document_bytes(
    db: AsyncSession, *, tenant_id: int, document_id: int
) -> Optional[Document]:
    """
    Fetch the Document row including file_data.
    Kept separate from list/get queries because file_data can be tens of MB.
    """
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.tenant_id == tenant_id,
        )
    )
    return result.scalar_one_or_none()


# =============================================================================
# LISTING UPLOAD JOBS
# =============================================================================

async def create_listing_upload_job(
    db: AsyncSession,
    *,
    tenant_id: int,
    public_id: str,
    filename: str,
    file_type: str,
    file_data: Optional[bytes] = None,
    storage_path: Optional[str] = None,
    chatbot_config_id: Optional[int] = None,
    industry: str = "real_estate",
) -> ListingUploadJob:
    job = ListingUploadJob(
        tenant_id=tenant_id,
        public_id=public_id,
        filename=filename,
        file_type=file_type,
        file_data=file_data,
        storage_path=storage_path,
        chatbot_config_id=chatbot_config_id,
        industry=industry,
    )
    db.add(job)
    await db.flush()
    return job


async def get_listing_upload_job(
    db: AsyncSession, *, tenant_id: int, job_id: int
) -> Optional[ListingUploadJob]:
    result = await db.execute(
        select(ListingUploadJob).where(
            ListingUploadJob.id == job_id,
            ListingUploadJob.tenant_id == tenant_id,
        )
    )
    return result.scalar_one_or_none()


async def get_listing_upload_job_by_public_id(
    db: AsyncSession, *, tenant_id: int, public_id: str
) -> Optional[ListingUploadJob]:
    result = await db.execute(
        select(ListingUploadJob).where(
            ListingUploadJob.public_id == public_id,
            ListingUploadJob.tenant_id == tenant_id,
        )
    )
    return result.scalar_one_or_none()


async def list_listing_upload_jobs(
    db: AsyncSession,
    *,
    tenant_id: int,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Sequence[ListingUploadJob]:
    q = select(ListingUploadJob).where(ListingUploadJob.tenant_id == tenant_id)
    if status:
        q = q.where(ListingUploadJob.status == status)
    q = q.order_by(ListingUploadJob.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(q)
    return result.scalars().all()


async def count_listing_upload_jobs(
    db: AsyncSession,
    *,
    tenant_id: int,
    status: Optional[str] = None,
) -> int:
    q = select(func.count()).select_from(ListingUploadJob).where(
        ListingUploadJob.tenant_id == tenant_id
    )
    if status:
        q = q.where(ListingUploadJob.status == status)
    result = await db.execute(q)
    return result.scalar_one()


async def update_listing_upload_job(
    db: AsyncSession, *, job: ListingUploadJob, **kwargs
) -> ListingUploadJob:
    for key, value in kwargs.items():
        setattr(job, key, value)
    await db.flush()
    return job