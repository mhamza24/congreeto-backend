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

from app.core.db_base import _new_public_id
from app.core.enums import DocStatus, CrawlStatus
from app.modules.audit import repository as audit
from app.modules.billing import repository as billing_repo
from app.modules.chatbot import repository as repo
from app.modules.chatbot import schemas
from app.modules.chatbot import tasks as bg
from app.utils.system_prompt_generator import build_static_system_prompt

logger = logging.getLogger(__name__)

# Default personality slug — used when chatbot has no explicit personality set
_DEFAULT_PERSONALITY_SLUG = "aria"


# =============================================================================
# CHATBOT CONFIG
# =============================================================================

async def create_chatbot(
    db: AsyncSession,
    *,
    tenant_id: int,
    payload: schemas.ChatbotCreateRequest,
    user_id: Optional[int] = None,
    request=None,
) -> schemas.ChatbotResponse:
    sub = await billing_repo.get_active_subscription(db, tenant_id=tenant_id)
    if sub and sub.plan:
        base_limit   = sub.plan.get_limit("max_chatbots")
        addon_grant  = await billing_repo.get_addon_grant_total(
            db, tenant_id=tenant_id, metric="max_chatbots"
        )
        max_chatbots = base_limit + addon_grant
        if max_chatbots > 0:
            current = await repo.count_chatbots_for_tenant(db, tenant_id=tenant_id)
            if current >= max_chatbots:
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail=(
                        f"Chatbot limit reached ({current}/{max_chatbots}). "
                        "Upgrade your plan or purchase the Extra Chatbot add-on."
                    ),
                )

    # ── Resolve personality ───────────────────────────────────────────────────
    personality_slug = payload.prompt_personality_slug or _DEFAULT_PERSONALITY_SLUG
    personality = await repo.get_prompt_personality_by_slug(db, slug=personality_slug)
    if not personality:
        # Fallback to platform default — should always exist after migration seed
        personality = await repo.get_prompt_personality_by_slug(db, slug=_DEFAULT_PERSONALITY_SLUG)

    # ── Generate static system prompt ─────────────────────────────────────────
    company_profile_dict = payload.company_profile.model_dump() if payload.company_profile else {}
    personality_content = personality.personality_content if personality else {}
    static_prompt = build_static_system_prompt(personality_content, company_profile_dict)

    iframe_token = uuid.uuid4().hex  # 32-char hex, no dashes — used as embed token

    chatbot = await repo.create_chatbot(
        db,
        tenant_id=tenant_id,
        name=payload.name,
        iframe_token=iframe_token,
        identity=payload.identity,
        system_prompt_template=static_prompt,
        welcome_message=payload.welcome_message,
        auto_close_minutes=payload.auto_close_minutes,
        allowed_domains=payload.allowed_domains,
        branding=payload.branding,
        lead_capture_config=payload.lead_capture_config,
        company_profile=company_profile_dict,
        prompt_personality_id=personality.id if personality else None,
        allow_rental=payload.allow_rental,
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

    await audit.write(
        db,
        entity_type="chatbot_configs",
        action=audit.CREATE,
        tenant_id=tenant_id,
        user_id=user_id,
        entity_id=chatbot.id,
        diff={"after": {"name": chatbot.name, "identity": str(chatbot.identity)}},
        request=request,
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


async def get_chatbot_embed(
    db: AsyncSession,
    *,
    iframe_token: str,
) -> schemas.ChatbotEmbedResponse:
    """
    Public endpoint — no auth required.
    Returns chatbot branding, config, and active theme based on iframe token.
    """
    chatbot = await repo.get_chatbot_by_iframe_token(db, iframe_token=iframe_token)
    if not chatbot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chatbot not found.")

    active_theme = await repo.get_active_theme(db, chatbot_config_id=chatbot.id)
    theme_data = None
    if active_theme:
        theme_data = schemas.EmbedTheme(
            name=active_theme.name,
            colors=active_theme.colors,
            typography=active_theme.typography,
            assets=active_theme.assets,
            layout=active_theme.layout,
        )

    return schemas.ChatbotEmbedResponse(
        iframe_token=chatbot.iframe_token,
        name=chatbot.name,
        status=str(chatbot.status.value) if hasattr(chatbot.status, "value") else str(chatbot.status),
        welcome_message=chatbot.welcome_message,
        auto_close_minutes=chatbot.auto_close_minutes,
        branding=chatbot.branding,
        lead_capture_config=chatbot.lead_capture_config,
        company_profile=chatbot.company_profile,
        active_theme=theme_data,
    )


async def update_chatbot(
    db: AsyncSession,
    *,
    tenant_id: int,
    public_id: str,
    payload: schemas.ChatbotUpdateRequest,
    user_id: Optional[int] = None,
    request=None,
) -> schemas.ChatbotResponse:
    chatbot = await repo.get_chatbot_by_public_id(
        db, tenant_id=tenant_id, public_id=public_id
    )
    if not chatbot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chatbot not found.")

    updates = payload.model_dump(exclude_none=True, exclude={"company_profile", "prompt_personality_slug"})

    # ── Handle company_profile update ─────────────────────────────────────────
    new_company_profile: dict | None = None
    if payload.company_profile is not None:
        new_company_profile = payload.company_profile.model_dump()
        updates["company_profile"] = new_company_profile

    # ── Handle personality switch ─────────────────────────────────────────────
    personality = None
    if payload.prompt_personality_slug:
        personality = await repo.get_prompt_personality_by_slug(
            db, slug=payload.prompt_personality_slug
        )
        if personality:
            updates["prompt_personality_id"] = personality.id

    # ── Regenerate static prompt if personality or company_profile changed ────
    if payload.company_profile is not None or payload.prompt_personality_slug:
        # Load personality content if not already loaded from slug switch
        if personality is None and chatbot.prompt_personality_id:
            personality = await repo.get_prompt_personality_by_id(
                db, personality_id=chatbot.prompt_personality_id
            )
        if personality is None:
            personality = await repo.get_prompt_personality_by_slug(
                db, slug=_DEFAULT_PERSONALITY_SLUG
            )

        effective_profile = new_company_profile if new_company_profile is not None else chatbot.company_profile
        personality_content = personality.personality_content if personality else {}
        updates["system_prompt_template"] = build_static_system_prompt(
            personality_content, effective_profile
        )

    chatbot = await repo.update_chatbot(db, chatbot=chatbot, **updates)

    await audit.write(
        db,
        entity_type="chatbot_configs",
        action=audit.UPDATE,
        tenant_id=tenant_id,
        user_id=user_id,
        entity_id=chatbot.id,
        diff={"after": {k: str(v) for k, v in updates.items() if k != "system_prompt_template"}},
        request=request,
    )

    await db.commit()
    await db.refresh(chatbot)
    return schemas.ChatbotResponse.model_validate(chatbot)


async def activate_chatbot(
    db: AsyncSession,
    *,
    tenant_id: int,
    public_id: str,
    user_id: Optional[int] = None,
    request=None,
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

    await audit.write(
        db,
        entity_type="chatbot_configs",
        action=audit.UPDATE,
        tenant_id=tenant_id,
        user_id=user_id,
        entity_id=chatbot.id,
        diff={"before": {"status": "draft"}, "after": {"status": "active"}},
        request=request,
    )

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

    # For website sources, default extract_listings to True so every crawl
    # automatically picks up and embeds listings found on the site.
    config = dict(payload.config)
    if payload.type == "website":
        config.setdefault("extract_listings", True)

    source = await repo.create_knowledge_source(
        db,
        tenant_id=tenant_id,
        chatbot_config_id=chatbot.id,
        type=payload.type,
        name=payload.name,
        config=config,
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


async def update_knowledge_source(
    db: AsyncSession,
    *,
    tenant_id: int,
    ks_public_id: str,
    payload: schemas.KnowledgeSourceUpdateRequest,
) -> schemas.KnowledgeSourceResponse:
    source = await repo.get_knowledge_source_by_public_id(
        db, tenant_id=tenant_id, public_id=ks_public_id
    )
    if not source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge source not found.")

    source = await repo.update_knowledge_source(
        db,
        source=source,
        type=payload.type,
        name=payload.name,
        config=payload.config,
    )
    return schemas.KnowledgeSourceResponse.model_validate(source)


async def delete_knowledge_source(
    db: AsyncSession,
    *,
    tenant_id: int,
    ks_public_id: str,
) -> None:
    source = await repo.get_knowledge_source_by_public_id(
        db, tenant_id=tenant_id, public_id=ks_public_id
    )
    if not source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge source not found.")

    await repo.delete_knowledge_source(db, source=source)


# =============================================================================
# CRAWL JOBS  (Option A — paste URLs)
# =============================================================================

async def submit_crawl_jobs(
    db: AsyncSession,
    *,
    tenant_id: int,
    user_id: int,
    ks_public_id: str,
    payload: schemas.CrawlJobCreateRequest,
) -> List[schemas.CrawlJobResponse]:
    """
    Create one crawl_job row per URL and enqueue Celery tasks.
    Pre-flight check: enforce the tenant's monthly pages_crawled quota before
    queuing anything — prevents over-crawling and gives a clear 402 response.
    """
    from datetime import date
    from app.modules.billing.task_helpers import check_and_enforce_limit
    from app.core.enums import UsageMetric, LimitStatus

    source = await repo.get_knowledge_source_by_public_id(
        db, tenant_id=tenant_id, public_id=ks_public_id
    )
    if not source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge source not found.")

    if source.type != "website":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Crawl jobs can only be created on a 'website' knowledge source.",
        )

    # ── Billing pre-flight: require active subscription ──────────────────
    from app.modules.billing import repository as billing_repo
    sub = await billing_repo.get_active_subscription(db, tenant_id=tenant_id)
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="An active subscription is required to crawl pages.",
        )

    # ── Billing pre-flight: check pages_crawled quota ─────────────────────
    used, limit, limit_status = await check_and_enforce_limit(
        db,
        tenant_id=tenant_id,
        metric=UsageMetric.PAGES_CRAWLED,
        metric_key="max_pages_crawled",
        default_limit=200,
    )
    if limit_status == LimitStatus.EXCEEDED:
        today = date.today()
        reset_month = today.month % 12 + 1
        reset_year = today.year + (today.month // 12)
        reset_date = date(reset_year, reset_month, 1)
        logger.warning(
            "submit_crawl_jobs: tenant %d blocked — pages_crawled limit reached (%d/%d)",
            tenant_id, used, limit,
        )
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                f"Monthly page crawl limit reached ({used}/{limit} pages used). "
                f"Your quota resets on {reset_date.strftime('%B 1, %Y')}. "
                "Upgrade your plan or purchase additional pages to continue crawling."
            ),
        )

    remaining = max(0, limit - used)
    if len(payload.urls) > remaining:
        logger.info(
            "submit_crawl_jobs: tenant %d trimming %d URLs to %d remaining quota",
            tenant_id, len(payload.urls), remaining,
        )
        # Trim URLs to the remaining budget rather than blocking entirely
        payload = payload.model_copy(update={"urls": payload.urls[:remaining]})

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
        logger.info("Enqueued crawl task job_public_id=%s url=%s", job.public_id, job.base_url)

    return [schemas.CrawlJobResponse.model_validate(j) for j in created_jobs]


async def list_crawl_jobs(
    db: AsyncSession, *, tenant_id: int, ks_public_id: str
) -> List[schemas.CrawlJobResponse]:
    source = await repo.get_knowledge_source_by_public_id(
        db, tenant_id=tenant_id, public_id=ks_public_id
    )
    if not source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge source not found.")
    jobs = await repo.list_crawl_jobs(
        db, tenant_id=tenant_id, knowledge_source_id=source.id
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
    ks_public_id: str,
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
    source = await repo.get_knowledge_source_by_public_id(
        db, tenant_id=tenant_id, public_id=ks_public_id
    )
    if not source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge source not found.")

    if source.type != "document":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Documents can only be uploaded to a 'document' knowledge source.",
        )

    # ── Gate 3: plan limits ───────────────────────────────────────────────────
    await _check_document_limits(db, tenant_id=tenant_id, new_file_size_bytes=file_size_bytes)

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


async def _check_document_limits(
    db: AsyncSession,
    *,
    tenant_id: int,
    new_file_size_bytes: int,
) -> None:
    """
    Raises HTTP 402 if the tenant would exceed their plan's document or storage limits.
    No-op if the tenant has no active subscription (graceful degradation).
    """
    sub = await billing_repo.get_active_subscription(db, tenant_id=tenant_id)
    if not sub or not sub.plan:
        return  # no plan → no gate (onboarding path)

    plan = sub.plan
    max_docs = plan.get_limit("max_documents")
    max_storage_mb = plan.get_limit("max_storage_mb")

    if max_docs > 0:
        current_docs = await repo.count_documents_for_tenant(db, tenant_id=tenant_id)
        if current_docs >= max_docs:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=(
                    f"Document limit reached ({current_docs}/{max_docs}). "
                    "Upgrade your plan or remove existing documents."
                ),
            )

    if max_storage_mb > 0:
        current_bytes = await repo.count_storage_bytes_for_tenant(db, tenant_id=tenant_id)
        max_bytes = max_storage_mb * 1024 * 1024
        if current_bytes + new_file_size_bytes > max_bytes:
            current_mb = current_bytes / (1024 * 1024)
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=(
                    f"Storage limit reached ({current_mb:.1f}/{max_storage_mb} MB). "
                    "Upgrade your plan or remove existing documents."
                ),
            )


async def list_documents(
    db: AsyncSession,
    *,
    tenant_id: int,
    ks_public_id: str,
) -> List[schemas.DocumentResponse]:
    source = await repo.get_knowledge_source_by_public_id(
        db, tenant_id=tenant_id, public_id=ks_public_id
    )
    if not source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge source not found.")
    docs = await repo.list_documents(
        db, tenant_id=tenant_id, knowledge_source_id=source.id
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
    top_k: int = 10,
    listing_top_k: int = 8,
) -> schemas.RAGQueryResponse:
    """
    Hybrid RAG retrieval: dense vector (HNSW cosine) + sparse FTS (tsvector),
    merged with Reciprocal Rank Fusion.

    Also runs a parallel semantic search on the listings table so listing
    data is always up-to-date (soft-deleted / archived listings are excluded
    automatically — no stale chunks to clean up).
    """
    from app.modules.open_ai import service as openai_service

    chatbot = await repo.get_chatbot_by_public_id(
        db, tenant_id=tenant_id, public_id=chatbot_public_id
    )
    if not chatbot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chatbot not found.")

    if not chatbot.rag_enabled:
        return schemas.RAGQueryResponse(chunks=[], total=0)

    # Embed query once — reused for both legs
    query_embedding = await openai_service.embed_text(query)

    # ── Leg 1: hybrid search on document_chunks ───────────────────────────────
    chunks = await repo.hybrid_search(
        db,
        tenant_id=tenant_id,
        chatbot_config_id=chatbot.id,
        query_embedding=query_embedding,
        query_text=query,
        top_k=top_k,
    )

    chunk_results = [
        schemas.RAGChunkResult(
            content=c.content,
            chunk_metadata=c.chunk_metadata,
            document_id=c.document_id,
            chunk_index=c.chunk_index,
        )
        for c in chunks
    ]

    # ── Leg 2: semantic search on listings (live data, no stale chunks) ───────
    # allow_rental is a chatbot-level toggle (default False). When False, restrict to 'sale' only.
    listing_type_filter: Optional[str] = None if chatbot.allow_rental else "sale"

    logger.info(
        "[rag] listing search tenant=%s allow_rental=%s type_filter=%s query=%r",
        tenant_id, chatbot.allow_rental, listing_type_filter, query,
    )

    # Fetch total count and semantic results in parallel
    import asyncio as _asyncio
    total_listings, listings = await _asyncio.gather(
        repo.count_active_listings(
            db, tenant_id=tenant_id, listing_type=listing_type_filter
        ),
        repo.listing_similarity_search(
            db,
            tenant_id=tenant_id,
            query_embedding=query_embedding,
            top_k=listing_top_k,
            listing_type=listing_type_filter,
        ),
    )

    logger.info("[rag] listing search returned %d sample(s), total_active=%d", len(listings), total_listings)

    # Inject total count as the first chunk so the LLM always has the real number
    listing_results: list[schemas.RAGChunkResult] = []
    if total_listings > 0:
        listing_results.append(
            schemas.RAGChunkResult(
                content=f"[Inventory Summary] Total active listings in database: {total_listings}",
                chunk_metadata={"source_type": "inventory_count"},
                document_id=0,
                chunk_index=0,
            )
        )

    listing_results.extend([
        schemas.RAGChunkResult(
            content=_listing_to_context(listing),
            chunk_metadata={
                "source_type": "listing",
                "listing_id": listing.id,
                "listing_public_id": listing.public_id,
                "listing_status": str(listing.status.value) if listing.status else None,
            },
            document_id=0,
            chunk_index=0,
        )
        for listing in listings
    ])

    all_results = chunk_results + listing_results
    return schemas.RAGQueryResponse(chunks=all_results, total=len(all_results))


def _listing_to_context(listing) -> str:
    """Render a listing row as a context string for the LLM prompt."""
    parts = []
    if listing.title:
        parts.append(f"**{listing.title}**")
    if listing.listing_type:
        parts.append(f"Type: {listing.listing_type.value}")
    if listing.status:
        parts.append(f"Status: {listing.status.value}")
    addr = " ".join(filter(None, [listing.street, listing.suburb, listing.state, listing.postcode]))
    if addr:
        parts.append(f"Address: {addr}")
    feats = []
    if listing.bedrooms:
        feats.append(f"{listing.bedrooms} bed")
    if listing.bathrooms:
        feats.append(f"{listing.bathrooms} bath")
    if listing.garages:
        feats.append(f"{listing.garages} garage")
    if listing.has_pool:
        feats.append("pool")
    if feats:
        parts.append("Features: " + ", ".join(feats))
    if listing.price_display:
        parts.append(f"Price: {listing.price_display}")
    elif listing.price:
        parts.append(f"Price: {listing.currency} {listing.price:,.0f}")
    if listing.description:
        parts.append(listing.description[:500])
    # Include the source URL so the LLM can share the direct link with visitors.
    # Check raw_data first, then fall back to the first URL found in media items.
    raw_data: dict = listing.raw_data or {}
    source_url = raw_data.get("source_url")
    if not source_url:
        for media_item in (listing.media or []):
            if isinstance(media_item, dict):
                candidate = media_item.get("url") or media_item.get("source_url") or media_item.get("href")
                if candidate and isinstance(candidate, str):
                    source_url = candidate
                    break
    if source_url:
        parts.append(f"Link: {source_url}")
    return "\n".join(parts)


# =============================================================================
# DOCUMENT DOWNLOAD
# =============================================================================

_FILE_TYPE_MIME = {
    "pdf":  "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt":  "text/plain",
    "text": "text/plain",
    "html": "text/plain",  # serve crawled HTML as plain text — don't expose raw HTML
}


async def download_document(
    db: AsyncSession,
    *,
    tenant_id: int,
    doc_public_id: str,
) -> tuple[bytes, str, str]:
    """
    Returns (file_bytes, mime_type, filename).
    Raises 404 if not found, 422 if the document has no stored bytes.
    """
    found = await repo.get_document_by_public_id(
        db, tenant_id=tenant_id, public_id=doc_public_id
    )
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    doc = await repo.get_document_bytes(
        db, tenant_id=tenant_id, document_id=found.id
    )
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    if not doc.file_data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "This document has no stored file data. "
                "It may have been crawled from a website (not uploaded) "
                "or migrated to external storage."
            ),
        )

    mime = _FILE_TYPE_MIME.get(doc.file_type, "application/octet-stream")
    return bytes(doc.file_data), mime, doc.file_name


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


# =============================================================================
# WIDGET THEME
# =============================================================================

async def list_themes(
    db: AsyncSession, *, tenant_id: int, chatbot_public_id: str
) -> List[schemas.ThemeResponse]:
    chatbot = await repo.get_chatbot_by_public_id(
        db, tenant_id=tenant_id, public_id=chatbot_public_id
    )
    if not chatbot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chatbot not found.")
    themes = await repo.list_themes(db, chatbot_config_id=chatbot.id)
    return [schemas.ThemeResponse.model_validate(t) for t in themes]


async def create_theme(
    db: AsyncSession,
    *,
    tenant_id: int,
    chatbot_public_id: str,
    payload: schemas.ThemeCreateRequest,
) -> schemas.ThemeResponse:
    chatbot = await repo.get_chatbot_by_public_id(
        db, tenant_id=tenant_id, public_id=chatbot_public_id
    )
    if not chatbot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chatbot not found.")

    theme = await repo.create_widget_theme(
        db,
        tenant_id=tenant_id,
        chatbot_config_id=chatbot.id,
        name=payload.name,
        is_active=False,  # caller must explicitly activate
        colors=payload.colors,
        typography=payload.typography,
        assets=payload.assets,
        layout=payload.layout,
        public_id=_new_public_id(),
    )
    await db.commit()
    await db.refresh(theme)
    return schemas.ThemeResponse.model_validate(theme)


async def update_theme(
    db: AsyncSession,
    *,
    tenant_id: int,
    chatbot_public_id: str,
    theme_public_id: str,
    payload: schemas.ThemeUpdateRequest,
) -> schemas.ThemeResponse:
    chatbot = await repo.get_chatbot_by_public_id(
        db, tenant_id=tenant_id, public_id=chatbot_public_id
    )
    if not chatbot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chatbot not found.")

    theme = await repo.get_theme_by_public_id(
        db, chatbot_config_id=chatbot.id, public_id=theme_public_id
    )
    if not theme:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Theme not found.")

    updates = payload.model_dump(exclude_none=True)
    theme = await repo.update_widget_theme(db, theme=theme, **updates)
    await db.commit()
    await db.refresh(theme)
    return schemas.ThemeResponse.model_validate(theme)


async def activate_theme(
    db: AsyncSession,
    *,
    tenant_id: int,
    chatbot_public_id: str,
    theme_public_id: str,
) -> schemas.ThemeResponse:
    chatbot = await repo.get_chatbot_by_public_id(
        db, tenant_id=tenant_id, public_id=chatbot_public_id
    )
    if not chatbot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chatbot not found.")

    theme = await repo.get_theme_by_public_id(
        db, chatbot_config_id=chatbot.id, public_id=theme_public_id
    )
    if not theme:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Theme not found.")

    # Deactivate all, then activate the target — inside one flush block
    await repo.deactivate_all_themes(db, chatbot_config_id=chatbot.id)
    theme = await repo.update_widget_theme(db, theme=theme, is_active=True)
    await db.commit()
    await db.refresh(theme)
    return schemas.ThemeResponse.model_validate(theme)


# =============================================================================
# CHATBOT ASSETS  (blob image upload)
# =============================================================================

_ALLOWED_IMAGE_TYPES = {
    "image/png", "image/jpeg", "image/gif",
    "image/webp", "image/svg+xml",
}
_ASSET_MAX_MB = 5  # per-image hard cap


async def upload_chatbot_asset(
    db: AsyncSession,
    *,
    tenant_id: int,
    chatbot_public_id: str,
    asset_type: str,
    file_name: str,
    content_type: str,
    file_size_bytes: int,
    file_data: bytes,
    base_url: str,
) -> schemas.AssetUploadResponse:
    if content_type not in _ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported image type '{content_type}'. Allowed: PNG, JPEG, GIF, WebP, SVG.",
        )
    if file_size_bytes > _ASSET_MAX_MB * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Image exceeds the {_ASSET_MAX_MB} MB per-file limit.",
        )

    chatbot = await repo.get_chatbot_by_public_id(
        db, tenant_id=tenant_id, public_id=chatbot_public_id
    )
    if not chatbot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chatbot not found.")

    public_id = _new_public_id()
    asset = await repo.create_asset(
        db,
        tenant_id=tenant_id,
        chatbot_config_id=chatbot.id,
        asset_type=asset_type,
        file_name=file_name,
        content_type=content_type,
        file_size_bytes=file_size_bytes,
        file_data=file_data,
        public_id=public_id,
    )

    serve_url = f"{base_url}/api/v1/chatbot/assets/{public_id}"

    # ── Auto-update chatbot branding with the asset URL ───────────────────────
    # This keeps branding.logo_url / branding.avatar_url etc. always current
    # without requiring a separate PATCH call from the frontend.
    await repo.update_chatbot_branding_asset_url(
        db,
        chatbot_config_id=chatbot.id,
        asset_type=asset_type,
        asset_url=serve_url,
    )

    await db.commit()
    await db.refresh(asset)

    return schemas.AssetUploadResponse(
        public_id=asset.public_id,
        asset_type=asset.asset_type,
        file_name=asset.file_name,
        content_type=asset.content_type,
        file_size_bytes=asset.file_size_bytes,
        serve_url=serve_url,
        created_at=asset.created_at,
    )


# =============================================================================
# MANUAL Q&A ENTRY
# =============================================================================

async def create_manual_entry(
    db: AsyncSession,
    *,
    tenant_id: int,
    user_id: int,
    ks_public_id: str,
    payload: schemas.ManualEntryCreateRequest,
) -> schemas.DocumentResponse:
    """
    Store a manual Q&A / text entry as a Document row (file_type='text').
    Content is UTF-8 encoded into file_data for the chunker task to read back.
    """
    source = await repo.get_knowledge_source_by_public_id(
        db, tenant_id=tenant_id, public_id=ks_public_id
    )
    if not source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge source not found.")

    if source.type != "manual_qa":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Manual entries can only be added to a 'manual_qa' knowledge source.",
        )

    content_bytes = payload.content.encode("utf-8")
    doc = await repo.create_document(
        db,
        knowledge_source_id=source.id,
        tenant_id=tenant_id,
        file_name=payload.title,
        file_type="text",
        file_size_bytes=len(content_bytes),
        file_data=content_bytes,
        uploaded_by=user_id,
        public_id=_new_public_id(),
    )
    await db.commit()
    await db.refresh(doc)

    bg.process_manual_entry.delay(
        document_id=doc.id,
        tenant_id=tenant_id,
        chatbot_config_id=source.chatbot_config_id,
    )
    logger.info(f"Enqueued process_manual_entry task for doc_id={doc.id}")

    return schemas.DocumentResponse.model_validate(doc)

# =============================================================================
# ADMIN — cross-tenant chatbot management
# =============================================================================

async def admin_list_chatbots(
    db: AsyncSession,
) -> list[schemas.ChatbotResponse]:
    chatbots = await repo.admin_list_all_chatbots(db)
    return [schemas.ChatbotResponse.model_validate(c) for c in chatbots]


async def admin_set_chatbot_status(
    db: AsyncSession,
    *,
    chatbot_public_id: str,
    new_status: str,
) -> schemas.ChatbotResponse:
    chatbot = await repo.admin_set_chatbot_status(
        db, public_id=chatbot_public_id, new_status=new_status
    )
    if not chatbot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chatbot not found.")
    return schemas.ChatbotResponse.model_validate(chatbot)


async def admin_delete_chatbot(
    db: AsyncSession,
    *,
    chatbot_public_id: str,
) -> None:
    deleted = await repo.admin_delete_chatbot(db, public_id=chatbot_public_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chatbot not found.")
