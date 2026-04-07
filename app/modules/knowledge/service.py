"""
app/modules/knowledge/service.py

Business logic only. No raw SQL. Calls repository + tasks.
All public functions take (db, *, tenant_id, ...) and return Pydantic schemas.
"""
from __future__ import annotations

import logging
import uuid
from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import DocStatus, CrawlStatus
from app.modules.knowledge import repository as repo
from app.modules.knowledge import schemas
from app.modules.knowledge import tasks as bg

logger = logging.getLogger(__name__)


def _new_public_id() -> str:
    return uuid.uuid4().hex


# =============================================================================
# CHATBOT CONFIG
# =============================================================================

async def create_chatbot(
    db: AsyncSession,
    *,
    tenant_id: int,
    payload: schemas.ChatbotCreateRequest,
) -> schemas.ChatbotResponse:
    iframe_token = uuid.uuid4().hex  # 32-char random, globally unique

    chatbot = await repo.create_chatbot(
        db,
        tenant_id=tenant_id,
        name=payload.name,
        iframe_token=iframe_token,
        identity=payload.identity,
        system_prompt_template=payload.system_prompt_template,
        welcome_message=payload.welcome_message,
        public_id=_new_public_id(),
    )

    # Always create a default active theme alongside the chatbot
    await repo.create_widget_theme(
        db,
        tenant_id=tenant_id,
        chatbot_config_id=chatbot.id,
        name="Default Theme",
        is_active=True,
        public_id=_new_public_id(),
    )

    await db.commit()
    await db.refresh(chatbot)
    return schemas.ChatbotResponse.model_validate(chatbot)


async def get_chatbot(
    db: AsyncSession, *, tenant_id: int, public_id: str
) -> schemas.ChatbotResponse:
    chatbot = await repo.get_chatbot_by_public_id(
        db, tenant_id=tenant_id, public_id=public_id
    )
    if not chatbot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chatbot not found.")
    return schemas.ChatbotResponse.model_validate(chatbot)


async def list_chatbots(
    db: AsyncSession, *, tenant_id: int
) -> List[schemas.ChatbotResponse]:
    chatbots = await repo.list_chatbots(db, tenant_id=tenant_id)
    return [schemas.ChatbotResponse.model_validate(c) for c in chatbots]


async def update_chatbot(
    db: AsyncSession,
    *,
    tenant_id: int,
    public_id: str,
    payload: schemas.ChatbotUpdateRequest,
) -> schemas.ChatbotResponse:
    chatbot = await repo.get_chatbot_by_public_id(
        db, tenant_id=tenant_id, public_id=public_id
    )
    if not chatbot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chatbot not found.")

    updates = payload.model_dump(exclude_none=True)
    chatbot = await repo.update_chatbot(db, chatbot=chatbot, **updates)
    await db.commit()
    await db.refresh(chatbot)
    return schemas.ChatbotResponse.model_validate(chatbot)


async def activate_chatbot(
    db: AsyncSession,
    *,
    tenant_id: int,
    public_id: str,
) -> schemas.ChatbotResponse:
    """
    Service layer check: chatbot can only go active if it has ready knowledge.
    """
    chatbot = await repo.get_chatbot_by_public_id(
        db, tenant_id=tenant_id, public_id=public_id
    )
    if not chatbot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chatbot not found.")

    has_knowledge = await repo.chatbot_has_ready_knowledge(
        db, tenant_id=tenant_id, chatbot_id=chatbot.id
    )
    if not has_knowledge:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Chatbot cannot go active yet. Add at least one knowledge source "
                "with a completed crawl or a ready document."
            ),
        )

    chatbot = await repo.update_chatbot(db, chatbot=chatbot, status="active")
    await db.commit()
    await db.refresh(chatbot)
    return schemas.ChatbotResponse.model_validate(chatbot)


# =============================================================================
# KNOWLEDGE SOURCE
# =============================================================================

async def create_knowledge_source(
    db: AsyncSession,
    *,
    tenant_id: int,
    chatbot_public_id: str,
    payload: schemas.KnowledgeSourceCreateRequest,
) -> schemas.KnowledgeSourceResponse:
    chatbot = await repo.get_chatbot_by_public_id(
        db, tenant_id=tenant_id, public_id=chatbot_public_id
    )
    if not chatbot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chatbot not found.")

    source = await repo.create_knowledge_source(
        db,
        tenant_id=tenant_id,
        chatbot_config_id=chatbot.id,
        type=payload.type,
        name=payload.name,
        config=payload.config,
        public_id=_new_public_id(),
    )
    await db.commit()
    await db.refresh(source)
    return schemas.KnowledgeSourceResponse.model_validate(source)


async def list_knowledge_sources(
    db: AsyncSession, *, tenant_id: int, chatbot_public_id: str
) -> List[schemas.KnowledgeSourceResponse]:
    chatbot = await repo.get_chatbot_by_public_id(
        db, tenant_id=tenant_id, public_id=chatbot_public_id
    )
    if not chatbot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chatbot not found.")

    sources = await repo.list_knowledge_sources(
        db, tenant_id=tenant_id, chatbot_config_id=chatbot.id
    )
    return [schemas.KnowledgeSourceResponse.model_validate(s) for s in sources]


# =============================================================================
# CRAWL JOBS  (Option A — paste URLs)
# =============================================================================

async def submit_crawl_jobs(
    db: AsyncSession,
    *,
    tenant_id: int,
    user_id: int,
    knowledge_source_id: int,
    payload: schemas.CrawlJobCreateRequest,
) -> List[schemas.CrawlJobResponse]:
    """
    Create one crawl_job row per URL and enqueue Celery tasks.
    """
    source = await repo.get_knowledge_source(
        db, tenant_id=tenant_id, source_id=knowledge_source_id
    )
    if not source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge source not found.")

    if source.type != "website":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Crawl jobs can only be created on a 'website' knowledge source.",
        )

    created_jobs = []
    for url in payload.urls:
        job = await repo.create_crawl_job(
            db,
            knowledge_source_id=source.id,
            tenant_id=tenant_id,
            base_url=url,
            triggered_by=user_id,
            public_id=_new_public_id(),
        )
        created_jobs.append(job)

    await db.commit()

    # Enqueue Celery tasks after commit so IDs are stable
    for job in created_jobs:
        bg.crawl_and_embed.delay(
            crawl_job_id=job.id,
            tenant_id=tenant_id,
            knowledge_source_id=source.id,
            chatbot_config_id=source.chatbot_config_id,
            base_url=job.base_url,
        )
        logger.info(f"Enqueued crawl task for job_id={job.id} url={job.base_url}")

    return [schemas.CrawlJobResponse.model_validate(j) for j in created_jobs]


async def list_crawl_jobs(
    db: AsyncSession, *, tenant_id: int, knowledge_source_id: int
) -> List[schemas.CrawlJobResponse]:
    jobs = await repo.list_crawl_jobs(
        db, tenant_id=tenant_id, knowledge_source_id=knowledge_source_id
    )
    return [schemas.CrawlJobResponse.model_validate(j) for j in jobs]


# =============================================================================
# DOCUMENTS  (Option B — upload PDF)
# =============================================================================

async def upload_document(
    db: AsyncSession,
    *,
    tenant_id: int,
    user_id: int,
    knowledge_source_id: int,
    file_name: str,
    file_type: str,
    file_size_bytes: int,
    file_data: Optional[bytes] = None,
    storage_path: Optional[str] = None,
) -> schemas.DocumentResponse:
    """
    Create the document row immediately (status=uploading),
    then enqueue the PDF processing Celery task.
    """
    source = await repo.get_knowledge_source(
        db, tenant_id=tenant_id, source_id=knowledge_source_id
    )
    if not source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge source not found.")

    if source.type != "document":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Documents can only be uploaded to a 'document' knowledge source.",
        )

    doc = await repo.create_document(
        db,
        knowledge_source_id=source.id,
        tenant_id=tenant_id,
        file_name=file_name,
        file_type=file_type,
        file_size_bytes=file_size_bytes,
        file_data=file_data,
        storage_path=storage_path,
        uploaded_by=user_id,
        public_id=_new_public_id(),
    )
    await db.commit()
    await db.refresh(doc)

    # Enqueue processing task
    bg.process_document.delay(
        document_id=doc.id,
        tenant_id=tenant_id,
        chatbot_config_id=source.chatbot_config_id,
    )
    logger.info(f"Enqueued process_document task for doc_id={doc.id}")

    return schemas.DocumentResponse.model_validate(doc)


async def list_documents(
    db: AsyncSession,
    *,
    tenant_id: int,
    knowledge_source_id: int,
) -> List[schemas.DocumentResponse]:
    docs = await repo.list_documents(
        db, tenant_id=tenant_id, knowledge_source_id=knowledge_source_id
    )
    return [schemas.DocumentResponse.model_validate(d) for d in docs]


async def get_document(
    db: AsyncSession, *, tenant_id: int, document_id: int
) -> schemas.DocumentResponse:
    doc = await repo.get_document(db, tenant_id=tenant_id, document_id=document_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    return schemas.DocumentResponse.model_validate(doc)


# =============================================================================
# RAG  (called by chat service — not exposed as a public HTTP endpoint)
# =============================================================================

async def rag_search(
    db: AsyncSession,
    *,
    tenant_id: int,
    chatbot_public_id: str,
    query: str,
    top_k: int = 5,
) -> schemas.RAGQueryResponse:
    from app.modules.open_ai import service as openai_service

    chatbot = await repo.get_chatbot_by_public_id(
        db, tenant_id=tenant_id, public_id=chatbot_public_id
    )
    if not chatbot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chatbot not found.")

    if not chatbot.rag_enabled:
        return schemas.RAGQueryResponse(chunks=[], total=0)

    query_embedding = await openai_service.embed_text(query)

    chunks = await repo.similarity_search(
        db,
        tenant_id=tenant_id,
        chatbot_config_id=chatbot.id,
        query_embedding=query_embedding,
        top_k=top_k,
    )

    results = [
        schemas.RAGChunkResult(
            content=c.content,
            chunk_metadata=c.chunk_metadata,
            document_id=c.document_id,
            chunk_index=c.chunk_index,
        )
        for c in chunks
    ]
    return schemas.RAGQueryResponse(chunks=results, total=len(results))


# =============================================================================
# LIVE LINK SCRAPPER  (existing — kept for backwards compat)
# =============================================================================

async def scrap_website_data(
    db: AsyncSession,
    *,
    payload: schemas.liveLinkScrapperRequest,
) -> schemas.liveLinkScrapperResponse:
    celery_task = bg.live_link_scrapper.delay(payload.link)
    logger.info(f"Task enqueued: {celery_task.id}, status: {celery_task.status}")
    return schemas.liveLinkScrapperResponse(
        id=celery_task.id,
        status=celery_task.status,
    )