"""
app/modules/knowledge/repository.py

Pure DB access — no business logic. All methods are tenant-scoped.
Service layer is the only caller.
"""
from __future__ import annotations

import logging
from typing import List, Optional, Sequence

from sqlalchemy import and_, exists, func, select, update
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.chatbot.models import (
    ChatbotAsset,
    ChatbotConfig,
    CrawlJob,
    Document,
    DocumentChunk,
    KnowledgeSource,
    Listing,
    WidgetTheme,
)
from app.core.enums import CrawlStatus, DocStatus, ChatbotStatus

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


async def update_crawl_job(
    db: AsyncSession, *, job: CrawlJob, **kwargs
) -> CrawlJob:
    for key, value in kwargs.items():
        setattr(job, key, value)
    await db.flush()
    return job


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
    chatbot = await get_chatbot_by_public_id(db, public_id=public_id)
    if not chatbot:
        return None
    chatbot.status = new_status
    await db.commit()
    await db.refresh(chatbot)
    return chatbot


async def admin_delete_chatbot(
    db: AsyncSession, *, public_id: str
) -> bool:
    chatbot = await get_chatbot_by_public_id(db, public_id=public_id)
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

async def listing_similarity_search(
    db: AsyncSession,
    *,
    tenant_id: int,
    query_embedding: List[float],
    top_k: int = 5,
) -> Sequence[Listing]:
    """
    Semantic search on the listings table.
    Excludes soft-deleted (deleted_at IS NOT NULL) and archived listings.
    Used as a parallel search leg alongside hybrid_search on document_chunks.
    """
    result = await db.execute(
        select(Listing)
        .where(
            Listing.tenant_id == tenant_id,
            Listing.deleted_at.is_(None),
            Listing.status != "archived",
            Listing.embedding.isnot(None),
        )
        .order_by(Listing.embedding.cosine_distance(query_embedding))
        .limit(top_k)
    )
    return result.scalars().all()


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