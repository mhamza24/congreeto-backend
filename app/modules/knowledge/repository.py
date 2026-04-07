"""
app/modules/knowledge/repository.py

Pure DB access — no business logic. All methods are tenant-scoped.
Service layer is the only caller.
"""
from __future__ import annotations

import logging
from typing import List, Optional, Sequence

from sqlalchemy import and_, exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.knowledge.models import (
    ChatbotConfig,
    CrawlJob,
    Document,
    DocumentChunk,
    KnowledgeSource,
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
    public_id: str,
) -> ChatbotConfig:
    chatbot = ChatbotConfig(
        tenant_id=tenant_id,
        name=name,
        iframe_token=iframe_token,
        identity=identity,
        system_prompt_template=system_prompt_template,
        welcome_message=welcome_message,
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
                    KnowledgeSource.type == "document",
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


async def similarity_search(
    db: AsyncSession,
    *,
    tenant_id: int,
    chatbot_config_id: int,
    query_embedding: List[float],
    top_k: int = 5,
) -> Sequence[DocumentChunk]:
    """
    Cosine similarity search scoped to tenant + chatbot.
    Always tenant-scoped — never leaks cross-tenant data.
    """
    result = await db.execute(
        select(DocumentChunk)
        .join(Document, Document.id == DocumentChunk.document_id)
        .join(KnowledgeSource, KnowledgeSource.id == Document.knowledge_source_id)
        .where(
            DocumentChunk.tenant_id == tenant_id,
            KnowledgeSource.chatbot_config_id == chatbot_config_id,
        )
        .order_by(DocumentChunk.embedding.cosine_distance(query_embedding))
        .limit(top_k)
    )
    return result.scalars().all()