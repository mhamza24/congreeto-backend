"""
app/modules/knowledge/tasks.py

Celery tasks for the RAG ingestion pipeline.

Two main tasks:
  crawl_and_embed   — Option A: scrape URLs → documents → chunks → embeddings
  process_document  — Option B: PDF upload → parse → chunks → embeddings

Both tasks:
  - Update crawl_job / document status throughout
  - Write DocumentChunk rows with embeddings
  - Flip chatbot_configs.rag_enabled after first chunk lands
  - Retry on transient failures with exponential backoff
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.celery_worker import celery_app, QUEUEEnum
from app.config.settings import get_settings
from app.core.database import get_task_db_session
from app.core.db_base import _new_public_id
from app.core.enums import CrawlStatus, DocStatus, ListingSource, UploadJobStatus, UsageMetric
from app.modules.billing import repository as billing_repo
from app.modules.chatbot import repository as repo
from app.modules.chatbot.models import DocumentChunk
from app.modules.chatbot.parsers import website_parser
from app.modules.chatbot.parsers.pdf_parser import _parse_pdf
from app.modules.chatbot.parsers.docx_parser import _parse_docx, _parse_txt
from app.modules.chatbot.task_helpers import (
    build_listing_embed_text,
    chunk_pages,
    chunk_plain_text,
    embed_chunks,
    extract_listings_from_page,
)

settings = get_settings()
logger = logging.getLogger(__name__)


# =============================================================================
# HELPERS
# =============================================================================

def _run(coro):
    """Run an async coroutine from a sync Celery task.

    Always creates a brand-new event loop so that a closed loop from a
    previous (failed) attempt never leaks into the retry.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        finally:
            loop.close()


async def _flip_rag_if_needed(
    db: AsyncSession, *, tenant_id: int, chatbot_config_id: int
) -> None:
    """Flip rag_enabled on the chatbot once the first chunks exist."""
    await repo.flip_rag_enabled(
        db, tenant_id=tenant_id, chatbot_id=chatbot_config_id
    )
    await db.commit()


async def _increment_usage(
    db: AsyncSession,
    *,
    tenant_id: int,
    metric: UsageMetric,
    amount: int = 1,
) -> None:
    """Increment a usage counter for the current billing month."""
    period_month = datetime.now(timezone.utc).strftime("%Y-%m")
    await billing_repo.increment_usage(
        db, tenant_id=tenant_id, metric=metric,
        period_month=period_month, amount=amount,
    )
    await db.commit()


# =============================================================================
# TASK A — CRAWL WEBSITES + EMBED
# =============================================================================

@celery_app.task(
    bind=True,
    name="app.modules.chatbot.tasks.crawl_and_embed",
    max_retries=settings.CELERY_MAX_TRIES,
    default_retry_delay=settings.CELERY_DEFAULT_RETRY_DELAY,
    queue=QUEUEEnum.ANALYSIS.value,
)
def crawl_and_embed(
    self,
    *,
    crawl_job_id: int,
    tenant_id: int,
    knowledge_source_id: int,
    chatbot_config_id: int,
    base_url: str,
) -> str:
    """
    Orchestrator task — scrapes all pages under base_url then dispatches one
    embed_crawled_page task per page.  Each per-page task runs independently
    in a short-lived worker, keeping Redis connections brief and avoiding
    broker disconnects on long crawls.

    1. Mark crawl_job → running
    2. Scrape all pages (HTTP)
    3. Update pages_found
    4. Dispatch N embed_crawled_page tasks (fire-and-forget)
    5. Per-page tasks atomically increment counters and the last one finalizes
    """
    try:
        _run(
            _crawl_and_embed_async(
                crawl_job_id=crawl_job_id,
                tenant_id=tenant_id,
                knowledge_source_id=knowledge_source_id,
                chatbot_config_id=chatbot_config_id,
                base_url=base_url,
            )
        )
        return f"crawl_and_embed dispatched for job_id={crawl_job_id}"

    except Exception as exc:
        import sentry_sdk
        countdown = 2 ** self.request.retries
        logger.error("crawl_and_embed failed error=%s retry_in=%ds", exc, countdown)
        if self.request.retries >= self.max_retries:
            sentry_sdk.capture_exception(exc)
        raise self.retry(exc=exc, countdown=countdown)


async def _crawl_and_embed_async(
    *,
    crawl_job_id: int,
    tenant_id: int,
    knowledge_source_id: int,
    chatbot_config_id: int,
    base_url: str,
) -> None:
    # ── Step 1: Mark job running (short DB session) ───────────────────────
    async with get_task_db_session() as db:
        job = await repo.get_crawl_job(db, tenant_id=tenant_id, job_id=crawl_job_id)
        if not job:
            logger.error(f"CrawlJob {crawl_job_id} not found.")
            return

        ks = await repo.get_knowledge_source(
            db, tenant_id=tenant_id, source_id=knowledge_source_id
        )
        extract_listings = bool(ks and ks.config.get("extract_listings", False))

        await repo.update_crawl_job(
            db,
            job=job,
            status=CrawlStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
        )
        await db.commit()

    # ── Step 2: Scrape (long HTTP — outside any DB session) ───────────────
    try:
        scraped: dict = await website_parser.scrape_websites(base_url)
    except Exception as exc:
        async with get_task_db_session() as db:
            job = await repo.get_crawl_job(db, tenant_id=tenant_id, job_id=crawl_job_id)
            if job:
                await repo.update_crawl_job(
                    db,
                    job=job,
                    status=CrawlStatus.FAILED,
                    error_message=str(exc),
                    completed_at=datetime.now(timezone.utc),
                )
                await db.commit()
        raise

    pages_dict: dict = scraped.get(base_url, {})
    pages_found = len(pages_dict)

    # ── Step 3: Record pages_found ────────────────────────────────────────
    async with get_task_db_session() as db:
        job = await repo.get_crawl_job(db, tenant_id=tenant_id, job_id=crawl_job_id)
        if job:
            await repo.update_crawl_job(db, job=job, pages_found=pages_found)
            await db.commit()

    if pages_found == 0:
        async with get_task_db_session() as db:
            job = await repo.get_crawl_job(db, tenant_id=tenant_id, job_id=crawl_job_id)
            if job:
                await repo.update_crawl_job(
                    db,
                    job=job,
                    status=CrawlStatus.COMPLETED,
                    completed_at=datetime.now(timezone.utc),
                )
                await db.commit()
        logger.info("CrawlJob %d: 0 pages found, marked completed.", crawl_job_id)
        return

    # ── Step 4: Batch-embed ALL pages in ONE OpenAI call ─────────────────
    # Chunk every page in memory (pure Python, no I/O), collect all texts,
    # then call embed_texts once across everything.
    # Result: 1 API call instead of N (one per page).
    from app.modules.open_ai import service as openai_service

    # {page_url: [chunk_dict, ...]} — chunk_dict has chunk_index/content/metadata
    # Order is preserved: all_texts[i] corresponds to page_chunks[url][j] in iteration order.
    page_chunks: dict[str, list[dict]] = {}
    all_texts: list[str] = []

    for page_url, page_text in pages_dict.items():
        chunks = chunk_plain_text(page_text, source_url=page_url)
        page_chunks[page_url] = chunks
        for chunk in chunks:
            all_texts.append(chunk["content"])

    embeddings: list[list[float]] = []
    if all_texts:
        try:
            # embed_texts handles internal batching at EMBED_BATCH_SIZE (from settings)
            embeddings = await openai_service.embed_texts(all_texts)
            logger.info(
                "CrawlJob %d: batch-embedded %d chunks across %d pages in 1 API call",
                crawl_job_id, len(all_texts), pages_found,
            )
        except Exception as exc:
            import sentry_sdk
            sentry_sdk.capture_exception(exc)
            logger.error(
                "CrawlJob %d: batch embedding failed (%s) — falling back to per-page embed",
                crawl_job_id, exc,
            )
            embeddings = []  # per-page tasks will embed themselves on fallback

    # Distribute embeddings back to per-page chunk dicts
    if embeddings and len(embeddings) == len(all_texts):
        text_idx = 0
        for page_url, chunks in page_chunks.items():
            for chunk in chunks:
                chunk["embedding"] = embeddings[text_idx]
                text_idx += 1
        pre_embedded = True
    else:
        pre_embedded = False

    # ── Step 5: Dispatch one short-lived task per page ────────────────────
    for page_url, page_text in pages_dict.items():
        chunks_for_page = page_chunks.get(page_url, [])
        embed_crawled_page.apply_async(
            kwargs=dict(
                page_url=page_url,
                page_text=page_text,
                pre_embedded_chunks=chunks_for_page if pre_embedded else [],
                crawl_job_id=crawl_job_id,
                tenant_id=tenant_id,
                knowledge_source_id=knowledge_source_id,
                chatbot_config_id=chatbot_config_id,
                extract_listings=extract_listings,
                pages_found=pages_found,
            ),
            queue=QUEUEEnum.ANALYSIS.value,
        )

    logger.info(
        "CrawlJob %d: dispatched %d embed_crawled_page tasks (pre_embedded=%s).",
        crawl_job_id, pages_found, pre_embedded,
    )


# =============================================================================
# TASK A2 — EMBED ONE CRAWLED PAGE  (dispatched by crawl_and_embed)
# =============================================================================

@celery_app.task(
    bind=True,
    name="app.modules.chatbot.tasks.embed_crawled_page",
    max_retries=settings.CELERY_MAX_TRIES,
    default_retry_delay=settings.CELERY_DEFAULT_RETRY_DELAY,
    queue=QUEUEEnum.ANALYSIS.value,
)
def embed_crawled_page(
    self,
    *,
    page_url: str,
    page_text: str,
    pre_embedded_chunks: list,
    crawl_job_id: int,
    tenant_id: int,
    knowledge_source_id: int,
    chatbot_config_id: int,
    extract_listings: bool,
    pages_found: int,
) -> str:
    """
    Process a single crawled page: write pre-embedded chunks to DB (or embed
    them inline on fallback) → optional listing extraction → atomically
    increment crawl job counters and finalize when the last page completes.

    pre_embedded_chunks: list of {chunk_index, content, metadata, embedding}
        dicts computed by the orchestrator in one batch call.  Empty list
        triggers per-page fallback embedding (used when batch embedding fails).
    """
    import sentry_sdk
    try:
        _run(
            _embed_crawled_page_async(
                page_url=page_url,
                page_text=page_text,
                pre_embedded_chunks=pre_embedded_chunks,
                crawl_job_id=crawl_job_id,
                tenant_id=tenant_id,
                knowledge_source_id=knowledge_source_id,
                chatbot_config_id=chatbot_config_id,
                extract_listings=extract_listings,
                pages_found=pages_found,
            )
        )
        return f"embed_crawled_page completed for {page_url}"

    except Exception as exc:
        if self.request.retries < self.max_retries:
            countdown = 2 ** self.request.retries
            logger.error(
                "embed_crawled_page failed for %s: %s. Retrying in %ds.",
                page_url, exc, countdown,
            )
            raise self.retry(exc=exc, countdown=countdown)

        # All retries exhausted — capture in Sentry, count page as failed
        sentry_sdk.capture_exception(exc)
        logger.error("embed_crawled_page: all retries exhausted for %s: %s.", page_url, exc)
        _run(
            _on_page_done(
                crawl_job_id=crawl_job_id,
                tenant_id=tenant_id,
                chatbot_config_id=chatbot_config_id,
                pages_found=pages_found,
                success=False,
            )
        )


async def _embed_crawled_page_async(
    *,
    page_url: str,
    page_text: str,
    pre_embedded_chunks: list,
    crawl_job_id: int,
    tenant_id: int,
    knowledge_source_id: int,
    chatbot_config_id: int,
    extract_listings: bool,
    pages_found: int,
) -> None:
    """
    Checkpoint-session pattern for large SaaS:

      Session 1 (tiny):  INSERT document, status=PROCESSING → commit → release connection
      [No session held]:  All external I/O (OpenAI embed + LLM extract)
      Session 2 (tiny):  INSERT chunks + listings + status=READY → single commit
      Session 3 (on err): UPDATE status=FAILED → commit

    Never holds a DB connection during the OpenAI calls — keeps the connection
    pool healthy even when many pages are processed concurrently.
    """
    import uuid
    from app.modules.open_ai import service as openai_service

    doc_id: int | None = None

    # ── Checkpoint 1: create document placeholder (PROCESSING) ───────────
    async with get_task_db_session() as db:
        doc = await repo.create_document(
            db,
            knowledge_source_id=knowledge_source_id,
            tenant_id=tenant_id,
            file_name=page_url,
            file_type="html",
            file_size_bytes=len(page_text.encode()),
            public_id=uuid.uuid4().hex,
        )
        await repo.update_document(db, doc=doc, status=DocStatus.PROCESSING)
        await db.commit()
        doc_id = doc.id
        logger.debug("embed_crawled_page: doc %d created (PROCESSING) for %s", doc_id, page_url)

    # ── External I/O (no DB session held) ────────────────────────────────
    try:
        if pre_embedded_chunks:
            # Fast path: orchestrator already batched the embeddings
            embedded_chunks = pre_embedded_chunks
            logger.debug(
                "embed_crawled_page: using %d pre-embedded chunks for %s",
                len(embedded_chunks), page_url,
            )
        else:
            # Fallback: embed this page individually (used when batch embed failed)
            raw_chunks = chunk_plain_text(page_text, source_url=page_url)
            embedded_chunks = await embed_chunks(raw_chunks, openai_service) if raw_chunks else []
            logger.debug(
                "embed_crawled_page: fallback-embedded %d chunks for %s",
                len(embedded_chunks), page_url,
            )

        extracted_listings: list[dict] = []
        if extract_listings:
            extracted_listings = await extract_listings_from_page(
                page_text, openai_service, source_url=page_url
            )
    except Exception as exc:
        # External I/O failed — mark document FAILED in its own tiny session
        logger.error("embed_crawled_page: I/O error for %s: %s", page_url, exc)
        async with get_task_db_session() as db:
            doc = await repo.get_document(db, tenant_id=tenant_id, document_id=doc_id)
            if doc:
                await repo.update_document(
                    db, doc=doc,
                    status=DocStatus.FAILED,
                    error_message=f"Embed/extract error: {exc}",
                )
                await db.commit()
        raise  # re-raise so Celery retries / calls _on_page_done(success=False)

    # ── Checkpoint 2: write all results atomically (single commit) ────────
    try:
        async with get_task_db_session() as db:
            doc = await repo.get_document(db, tenant_id=tenant_id, document_id=doc_id)
            if not doc:
                logger.error("embed_crawled_page: doc %d disappeared for %s", doc_id, page_url)
                return

            # Chunks
            if not embedded_chunks:
                await repo.update_document(db, doc=doc, status=DocStatus.READY, chunk_count=0)
            else:
                chunk_rows = [
                    DocumentChunk(
                        document_id=doc.id,
                        tenant_id=tenant_id,
                        chunk_index=c["chunk_index"],
                        content=c["content"],
                        embedding=c["embedding"],
                        chunk_metadata=c["metadata"],
                    )
                    for c in embedded_chunks
                ]
                await repo.bulk_create_chunks(db, chunks=chunk_rows)
                await repo.update_document(
                    db, doc=doc, status=DocStatus.READY, chunk_count=len(chunk_rows)
                )
                logger.info(
                    "embed_crawled_page: %d chunks written for %s", len(chunk_rows), page_url
                )

            # Listings (same commit — atomically tied to chunks)
            page_listing_ids: list[int] = []
            if extracted_listings:
                page_external_ids = [
                    f"{crawl_job_id}::{page_url}::{item.get('title', '')}"
                    for item in extracted_listings
                ]
                existing_map = await repo.get_listings_by_external_ids(
                    db, tenant_id=tenant_id, external_ids=page_external_ids,
                )
                for item, external_id in zip(extracted_listings, page_external_ids):
                    existing = existing_map.get(external_id)
                    listing, _ = await repo.upsert_listing(
                        db,
                        tenant_id=tenant_id,
                        external_id=external_id,
                        crawl_job_id=crawl_job_id,
                        source=ListingSource.CRAWLED.value,
                        title=item.get("title") or page_url,
                        listing_type=item.get("listing_type", "sale"),
                        status=item.get("status", "active"),
                        description=item.get("description"),
                        price=item.get("price"),
                        price_display=item.get("price_display"),
                        currency=item.get("currency", "AUD"),
                        street=item.get("street"),
                        suburb=item.get("suburb"),
                        state=item.get("state"),
                        postcode=item.get("postcode"),
                        bedrooms=item.get("bedrooms"),
                        bathrooms=item.get("bathrooms"),
                        garages=item.get("garages"),
                        land_sqm=item.get("land_sqm"),
                        house_sqm=item.get("house_sqm"),
                        has_pool=item.get("has_pool", False),
                        raw_data=item.get("raw_data", {}),
                        public_id=_new_public_id() if not existing else existing.public_id,
                    )
                    page_listing_ids.append(listing.id)

            # Single commit — chunks + listings land together or not at all
            await db.commit()
            logger.info(
                "embed_crawled_page: committed doc=%d chunks=%d listings=%d for %s",
                doc_id, len(embedded_chunks), len(page_listing_ids), page_url,
            )

        # Dispatch listing embed tasks after the commit is stable
        for i in range(0, len(page_listing_ids), _EMBED_BATCH_SIZE):
            batch_ids = page_listing_ids[i: i + _EMBED_BATCH_SIZE]
            embed_listings_batch.apply_async(
                kwargs=dict(listing_ids=batch_ids, tenant_id=tenant_id),
                queue=QUEUEEnum.ANALYSIS.value,
            )

    except Exception as exc:
        logger.error("embed_crawled_page: DB write failed for %s: %s", page_url, exc)
        async with get_task_db_session() as db:
            doc = await repo.get_document(db, tenant_id=tenant_id, document_id=doc_id)
            if doc:
                await repo.update_document(
                    db, doc=doc,
                    status=DocStatus.FAILED,
                    error_message=f"DB write error: {exc}",
                )
                await db.commit()
        raise

    # ── Atomically record success and check finalization ──────────────────
    await _on_page_done(
        crawl_job_id=crawl_job_id,
        tenant_id=tenant_id,
        chatbot_config_id=chatbot_config_id,
        pages_found=pages_found,
        success=True,
    )


async def _on_page_done(
    *,
    crawl_job_id: int,
    tenant_id: int,
    chatbot_config_id: int,
    pages_found: int,
    success: bool,
) -> None:
    """
    Atomically increment the crawl job page counter, then finalize the job
    if this is the last page.  Safe to call concurrently from many workers.
    """
    async with get_task_db_session() as db:
        processed, failed, found = await repo.atomic_increment_crawl_page(
            db, job_id=crawl_job_id, success=success
        )
        await db.commit()

    # Use pages_found passed by the orchestrator (DB value may lag on first
    # page to complete if the orchestrator hasn't flushed yet).
    effective_found = max(found, pages_found)
    if processed + failed < effective_found:
        return

    # Last page — finalize the job (check status first for idempotency)
    async with get_task_db_session() as db:
        job = await repo.get_crawl_job(db, tenant_id=tenant_id, job_id=crawl_job_id)
        if not job or job.status in (CrawlStatus.COMPLETED, CrawlStatus.FAILED):
            return  # already finalized by a concurrent task

        final_status = CrawlStatus.COMPLETED if failed == 0 else CrawlStatus.FAILED
        await repo.update_crawl_job(
            db,
            job=job,
            status=final_status,
            completed_at=datetime.now(timezone.utc),
        )
        await db.commit()

        if processed > 0:
            await _flip_rag_if_needed(
                db, tenant_id=tenant_id, chatbot_config_id=chatbot_config_id
            )
            await _increment_usage(
                db, tenant_id=tenant_id,
                metric=UsageMetric.PAGES_CRAWLED,
                amount=processed,
            )

    logger.info(
        f"CrawlJob {crawl_job_id} finalized. "
        f"processed={processed} failed={failed}"
    )


# =============================================================================
# TASK B — PROCESS PDF DOCUMENT + EMBED
# =============================================================================

@celery_app.task(
    bind=True,
    name="app.modules.chatbot.tasks.process_document",
    max_retries=settings.CELERY_MAX_TRIES,
    default_retry_delay=settings.CELERY_DEFAULT_RETRY_DELAY,
    queue=QUEUEEnum.ANALYSIS.value,
)
def process_document(
    self,
    *,
    document_id: int,
    tenant_id: int,
    chatbot_config_id: int,
) -> str:
    """
    1. Fetch document bytes (from DB blob or S3)
    2. Parse PDF → pages → chunks
    3. Embed chunks
    4. Write DocumentChunk rows
    5. Mark document → ready
    6. Flip rag_enabled
    """
    try:
        _run(
            _process_document_async(
                document_id=document_id,
                tenant_id=tenant_id,
                chatbot_config_id=chatbot_config_id,
            )
        )
        return f"process_document completed for document_id={document_id}"

    except Exception as exc:
        countdown = 2 ** self.request.retries
        logger.error(
            f"process_document failed for doc_id={document_id}: {exc}. "
            f"Retrying in {countdown}s."
        )
        raise self.retry(exc=exc, countdown=countdown)


async def _process_document_async(
    *,
    document_id: int,
    tenant_id: int,
    chatbot_config_id: int,
) -> None:
    from app.modules.open_ai import service as openai_service

    async with get_task_db_session() as db:
        # ── Step 1: Fetch document ────────────────────────────────────────
        doc = await repo.get_document(db, tenant_id=tenant_id, document_id=document_id)
        if not doc:
            logger.error(f"Document {document_id} not found.")
            return

        await repo.update_document(db, doc=doc, status=DocStatus.PROCESSING)
        await db.commit()

        # ── Step 2: Get file bytes ────────────────────────────────────────
        try:
            file_bytes = await _get_pdf_bytes(doc)
        except Exception as exc:
            await repo.update_document(
                db, doc=doc,
                status=DocStatus.FAILED,
                error_message=f"Could not fetch file: {exc}",
            )
            await db.commit()
            raise

        # ── Step 3: Parse by file type ────────────────────────────────────
        try:
            if doc.file_type == "docx":
                parsed = _parse_docx(file_bytes)
            elif doc.file_type == "txt":
                parsed = _parse_txt(file_bytes)
            else:
                parsed = _parse_pdf(file_bytes, extract_tables=True, password=None)
        except Exception as exc:
            await repo.update_document(
                db, doc=doc,
                status=DocStatus.FAILED,
                error_message=f"Parse error ({doc.file_type}): {exc}",
            )
            await db.commit()
            raise

        pages = parsed.get("pages", [])
        page_count = parsed.get("total_pages", 0)

        await repo.update_document(db, doc=doc, page_count=page_count)
        await db.commit()

        # ── Step 4: Chunk ─────────────────────────────────────────────────
        raw_chunks = chunk_pages(pages)

        if not raw_chunks:
            await repo.update_document(
                db, doc=doc,
                status=DocStatus.READY,
                chunk_count=0,
            )
            await db.commit()
            logger.warning(f"Document {document_id} produced 0 chunks (empty PDF?).")
            return

        # ── Step 5: Embed ─────────────────────────────────────────────────
        try:
            embedded_chunks = await embed_chunks(raw_chunks, openai_service)
        except Exception as exc:
            await repo.update_document(
                db, doc=doc,
                status=DocStatus.FAILED,
                error_message=f"Embedding error: {exc}",
            )
            await db.commit()
            raise

        # ── Step 6: Write chunks ──────────────────────────────────────────
        # Delete any stale chunks first (in case of re-processing)
        await repo.delete_chunks_for_document(db, document_id=doc.id)

        chunk_rows = [
            DocumentChunk(
                document_id=doc.id,
                tenant_id=tenant_id,
                chunk_index=c["chunk_index"],
                content=c["content"],
                embedding=c["embedding"],
                chunk_metadata=c["metadata"],
            )
            for c in embedded_chunks
        ]
        await repo.bulk_create_chunks(db, chunks=chunk_rows)

        # ── Step 7: Mark ready ────────────────────────────────────────────
        await repo.update_document(
            db, doc=doc,
            status=DocStatus.READY,
            chunk_count=len(chunk_rows),
        )
        await db.commit()

        # ── Step 8: Flip rag_enabled ──────────────────────────────────────
        await _flip_rag_if_needed(
            db, tenant_id=tenant_id, chatbot_config_id=chatbot_config_id
        )

        # Track documents_uploaded usage
        await _increment_usage(
            db, tenant_id=tenant_id,
            metric=UsageMetric.DOCUMENTS_UPLOADED,
        )

        logger.info(
            f"Document {document_id} processed. "
            f"pages={page_count} chunks={len(chunk_rows)}"
        )


async def _get_pdf_bytes(doc: Any) -> bytes:
    """
    Fetch raw PDF bytes from wherever they live.
    Currently: DB blob. Later: S3/GCS via storage_path.
    """
    if doc.file_data:
        return bytes(doc.file_data)

    if doc.storage_path:
        # TODO: swap in S3/GCS fetch when you migrate off blob storage
        raise NotImplementedError(
            f"S3/GCS fetch not yet implemented. storage_path={doc.storage_path}"
        )

    raise ValueError(
        f"Document {doc.id} has neither file_data nor storage_path."
    )


# =============================================================================
# TASK C — PROCESS MANUAL Q&A ENTRY + EMBED
# =============================================================================

@celery_app.task(
    bind=True,
    name="app.modules.chatbot.tasks.process_manual_entry",
    max_retries=settings.CELERY_MAX_TRIES,
    default_retry_delay=settings.CELERY_DEFAULT_RETRY_DELAY,
    queue=QUEUEEnum.ANALYSIS.value,
)
def process_manual_entry(
    self,
    *,
    document_id: int,
    tenant_id: int,
    chatbot_config_id: int,
) -> str:
    """
    Chunk and embed a manually entered text document.
    Same pipeline as process_document but decodes file_data as UTF-8 directly.
    """
    try:
        _run(
            _process_manual_entry_async(
                document_id=document_id,
                tenant_id=tenant_id,
                chatbot_config_id=chatbot_config_id,
            )
        )
        return f"process_manual_entry completed for document_id={document_id}"

    except Exception as exc:
        countdown = 2 ** self.request.retries
        logger.error(
            f"process_manual_entry failed for doc_id={document_id}: {exc}. "
            f"Retrying in {countdown}s."
        )
        raise self.retry(exc=exc, countdown=countdown)


async def _process_manual_entry_async(
    *,
    document_id: int,
    tenant_id: int,
    chatbot_config_id: int,
) -> None:
    from app.modules.open_ai import service as openai_service

    async with get_task_db_session() as db:
        doc = await repo.get_document(db, tenant_id=tenant_id, document_id=document_id)
        if not doc:
            logger.error(f"Manual entry document {document_id} not found.")
            return

        await repo.update_document(db, doc=doc, status=DocStatus.PROCESSING)
        await db.commit()

        try:
            text = bytes(doc.file_data).decode("utf-8")
        except Exception as exc:
            await repo.update_document(
                db, doc=doc,
                status=DocStatus.FAILED,
                error_message=f"Could not decode text content: {exc}",
            )
            await db.commit()
            raise

        raw_chunks = chunk_plain_text(text, source_url=None)

        if not raw_chunks:
            await repo.update_document(db, doc=doc, status=DocStatus.READY, chunk_count=0)
            await db.commit()
            return

        try:
            embedded_chunks = await embed_chunks(raw_chunks, openai_service)
        except Exception as exc:
            await repo.update_document(
                db, doc=doc,
                status=DocStatus.FAILED,
                error_message=f"Embedding error: {exc}",
            )
            await db.commit()
            raise

        await repo.delete_chunks_for_document(db, document_id=doc.id)

        chunk_rows = [
            DocumentChunk(
                document_id=doc.id,
                tenant_id=tenant_id,
                chunk_index=c["chunk_index"],
                content=c["content"],
                embedding=c["embedding"],
                chunk_metadata=c["metadata"],
            )
            for c in embedded_chunks
        ]
        await repo.bulk_create_chunks(db, chunks=chunk_rows)

        await repo.update_document(
            db, doc=doc,
            status=DocStatus.READY,
            chunk_count=len(chunk_rows),
        )
        await db.commit()

        await _flip_rag_if_needed(
            db, tenant_id=tenant_id, chatbot_config_id=chatbot_config_id
        )
        await _increment_usage(
            db, tenant_id=tenant_id,
            metric=UsageMetric.DOCUMENTS_UPLOADED,
        )

        logger.info(f"Manual entry {document_id} processed. chunks={len(chunk_rows)}")


# =============================================================================
# TASK D — EMBED LISTING  (called on create / update)
# =============================================================================

@celery_app.task(
    bind=True,
    name="app.modules.chatbot.tasks.embed_listing",
    max_retries=settings.CELERY_MAX_TRIES,
    default_retry_delay=settings.CELERY_DEFAULT_RETRY_DELAY,
    queue=QUEUEEnum.ANALYSIS.value,
)
def embed_listing(self, *, listing_id: int, tenant_id: int) -> str:
    """
    Compute and store the embedding for a single listing row.
    Call this whenever a listing is created or any indexed field is updated
    (title, description, suburb, state, price, listing_type, status).

    Enqueue from listing service:
        embed_listing.delay(listing_id=listing.id, tenant_id=listing.tenant_id)
    """
    try:
        _run(_embed_listing_async(listing_id=listing_id, tenant_id=tenant_id))
        return f"embed_listing completed for listing_id={listing_id}"
    except Exception as exc:
        countdown = 2 ** self.request.retries
        logger.error(f"embed_listing failed for listing_id={listing_id}: {exc}. Retrying in {countdown}s.")
        raise self.retry(exc=exc, countdown=countdown)


async def _embed_listing_async(*, listing_id: int, tenant_id: int) -> None:
    from app.modules.open_ai import service as openai_service

    async with get_task_db_session() as db:
        listing = await repo.get_listing_by_id(
            db, tenant_id=tenant_id, listing_id=listing_id
        )
        if not listing:
            logger.warning(f"Listing {listing_id} not found or soft-deleted — skipping embed.")
            return

        embed_text = build_listing_embed_text(listing)
        if not embed_text.strip():
            logger.warning(f"Listing {listing_id} produced empty embed text — skipping.")
            return

        embedding = await openai_service.embed_text(embed_text)

        await repo.update_listing_embedding(
            db, tenant_id=tenant_id, listing_id=listing_id, embedding=embedding
        )
        await db.commit()
        logger.info(f"Listing {listing_id} embedded ({len(embed_text)} chars).")


# =============================================================================
# TASK D2 — EMBED LISTINGS BATCH  (bulk import / crawl)
# =============================================================================

_EMBED_BATCH_SIZE = 100  # max listings per OpenAI embeddings call


@celery_app.task(
    bind=True,
    name="app.modules.chatbot.tasks.embed_listings_batch",
    max_retries=settings.CELERY_MAX_TRIES,
    default_retry_delay=settings.CELERY_DEFAULT_RETRY_DELAY,
    queue=QUEUEEnum.ANALYSIS.value,
)
def embed_listings_batch(self, *, listing_ids: list[int], tenant_id: int) -> str:
    """
    Compute and store embeddings for a batch of listings in one OpenAI call.

    Used instead of individual embed_listing tasks whenever listings are
    created in bulk (file upload, crawl extraction).  Each invocation handles
    at most _EMBED_BATCH_SIZE listings so the OpenAI payload stays bounded.

    Enqueue from bulk-create paths:
        embed_listings_batch.apply_async(
            kwargs=dict(listing_ids=[...], tenant_id=tenant_id),
            queue=QUEUEEnum.ANALYSIS.value,
        )
    """
    try:
        _run(_embed_listings_batch_async(listing_ids=listing_ids, tenant_id=tenant_id))
        return f"embed_listings_batch completed for {len(listing_ids)} listings"
    except Exception as exc:
        countdown = 2 ** self.request.retries
        logger.error(
            f"embed_listings_batch failed for tenant={tenant_id} "
            f"ids={listing_ids}: {exc}. Retrying in {countdown}s."
        )
        raise self.retry(exc=exc, countdown=countdown)


async def _embed_listings_batch_async(
    *, listing_ids: list[int], tenant_id: int
) -> None:
    from app.modules.open_ai import service as openai_service

    async with get_task_db_session() as db:
        listings = await repo.get_listings_by_ids(
            db, tenant_id=tenant_id, listing_ids=listing_ids
        )
        if not listings:
            logger.warning(
                f"embed_listings_batch: none of listing_ids={listing_ids} found."
            )
            return

        # Build embed texts; skip listings with empty text
        to_embed = []
        for lst in listings:
            text = build_listing_embed_text(lst)
            if text.strip():
                to_embed.append((lst.id, text))

        if not to_embed:
            logger.warning(
                f"embed_listings_batch: all listings produced empty embed text "
                f"(tenant={tenant_id}, ids={listing_ids})."
            )
            return

        # ── Single OpenAI call for the whole batch ────────────────────────────
        ids, texts = zip(*to_embed)
        embeddings = await openai_service.embed_texts(list(texts))

        # ── One bulk UPDATE round-trip ─────────────────────────────────────────
        id_to_embedding = dict(zip(ids, embeddings))
        await repo.bulk_update_listing_embeddings(
            db, tenant_id=tenant_id, id_to_embedding=id_to_embedding
        )
        await db.commit()
        logger.info(
            f"embed_listings_batch: embedded {len(id_to_embedding)} listings "
            f"(tenant={tenant_id})."
        )


# =============================================================================
# TASK E — CLEAR LISTING EMBEDDING  (called on soft-delete / archive)
# =============================================================================

@celery_app.task(
    bind=True,
    name="app.modules.chatbot.tasks.clear_listing_embedding",
    max_retries=2,
    default_retry_delay=5,
    queue=QUEUEEnum.ANALYSIS.value,
)
def clear_listing_embedding(self, *, listing_id: int, tenant_id: int) -> str:
    """
    NULL-out the embedding when a listing is soft-deleted or archived.
    Removes it from HNSW index scans immediately — no migration needed.

    Enqueue from listing service after soft-delete / status → archived:
        clear_listing_embedding.delay(listing_id=listing.id, tenant_id=listing.tenant_id)
    """
    try:
        _run(_clear_listing_embedding_async(listing_id=listing_id, tenant_id=tenant_id))
        return f"clear_listing_embedding completed for listing_id={listing_id}"
    except Exception as exc:
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)


async def _clear_listing_embedding_async(*, listing_id: int, tenant_id: int) -> None:
    async with get_task_db_session() as db:
        await repo.clear_listing_embedding(db, tenant_id=tenant_id, listing_id=listing_id)
        await db.commit()
        logger.info(f"Listing {listing_id} embedding cleared.")


# =============================================================================
# TASK F — PROCESS LISTING FILE UPLOAD (Excel or CSV, LLM-parsed, background)
# =============================================================================

@celery_app.task(
    bind=True,
    name="app.modules.chatbot.tasks.process_listing_file",
    max_retries=settings.CELERY_MAX_TRIES,
    default_retry_delay=settings.CELERY_DEFAULT_RETRY_DELAY,
    queue=QUEUEEnum.ANALYSIS.value,
)
def process_listing_file(self, *, job_id: int, tenant_id: int) -> str:
    """
    Background task: parse an uploaded Excel or CSV listing file with LLM normalization,
    then upsert each listing row in batches and trigger embed_listing for each one.
    """
    try:
        _run(_process_listing_file_async(job_id=job_id, tenant_id=tenant_id))
        return f"process_listing_file completed for job_id={job_id}"
    except Exception as exc:
        countdown = 2 ** self.request.retries
        logger.error(
            f"process_listing_file failed for job_id={job_id}: {exc}. "
            f"Retrying in {countdown}s."
        )
        raise self.retry(exc=exc, countdown=countdown)


async def _process_listing_file_async(*, job_id: int, tenant_id: int) -> None:
    from app.modules.chatbot.parsers.excel_parser import parse_excel_listings
    from app.modules.chatbot.parsers.csv_parser import parse_csv_listings
    from app.modules.chatbot.task_helpers import parse_listings_from_table
    from app.modules.open_ai import service as openai_service

    _BATCH_SIZE = 20  # listings committed per DB transaction

    async with get_task_db_session() as db:
        job = await repo.get_listing_upload_job(db, tenant_id=tenant_id, job_id=job_id)
        if not job:
            logger.error(f"ListingUploadJob {job_id} not found.")
            return

        await repo.update_listing_upload_job(db, job=job, status=UploadJobStatus.PROCESSING)
        await db.commit()

        # ── Step 1: Fetch file bytes ──────────────────────────────────────
        try:
            file_bytes = _get_listing_file_bytes(job)
        except Exception as exc:
            await repo.update_listing_upload_job(
                db, job=job, status=UploadJobStatus.FAILED,
                error_message=f"Could not fetch file: {exc}",
            )
            await db.commit()
            raise

        # ── Step 2: Parse file ────────────────────────────────────────────
        try:
            if job.file_type in ("xlsx", "xls"):
                raw_rows = parse_excel_listings(file_bytes)
            else:
                raw_rows = parse_csv_listings(file_bytes)
        except Exception as exc:
            await repo.update_listing_upload_job(
                db, job=job, status=UploadJobStatus.FAILED,
                error_message=f"File parse error: {exc}",
            )
            await db.commit()
            raise

        total_rows = len(raw_rows)
        await repo.update_listing_upload_job(db, job=job, total_rows=total_rows)
        await db.commit()

        if not raw_rows:
            await repo.update_listing_upload_job(db, job=job, status=UploadJobStatus.COMPLETED)
            await db.commit()
            logger.info(f"ListingUploadJob {job_id}: file is empty, nothing to import.")
            return

        # ── Step 3: LLM normalization ─────────────────────────────────────
        try:
            structured_rows = await parse_listings_from_table(raw_rows, openai_service)
        except Exception as exc:
            logger.warning(
                f"ListingUploadJob {job_id}: LLM normalization failed ({exc}), "
                "falling back to raw parsed rows."
            )
            structured_rows = raw_rows

        # ── Step 4: Upsert in batches ─────────────────────────────────────
        # Each batch: 1 SELECT (bulk existence check) + 1 flush + 1 commit
        # instead of N SELECTs + N flushes + N commits.
        processed = 0
        _VALID_STATUSES = {"active", "inactive", "sold", "leased"}
        _VALID_TYPES = {"sale", "rent"}

        for i in range(0, len(structured_rows), _BATCH_SIZE):
            batch = structured_rows[i: i + _BATCH_SIZE]

            # ── 4a: Normalize + build external_ids for the whole batch ────
            normalized: list[dict] = []
            for item in batch:
                raw_status = str(item.get("status") or "active").strip().lower()
                raw_type = str(item.get("listing_type") or "sale").strip().lower()
                external_id = (
                    f"upload::{job_id}::{item.get('title', '')}"
                    f"::{item.get('suburb', '')}"
                )
                normalized.append({
                    "item": item,
                    "external_id": external_id,
                    "status": raw_status if raw_status in _VALID_STATUSES else "active",
                    "listing_type": raw_type if raw_type in _VALID_TYPES else "sale",
                    "currency": str(item.get("currency") or "AUD").strip().upper(),
                })

            # ── 4b: ONE query for all existing listings in this batch ─────
            existing_map = await repo.get_listings_by_external_ids(
                db,
                tenant_id=tenant_id,
                external_ids=[n["external_id"] for n in normalized],
            )

            # ── 4c: Apply updates / create new rows in memory ─────────────
            upserted_listings: list = []
            for row_num, n in enumerate(normalized, start=i):
                item = n["item"]
                external_id = n["external_id"]
                existing = existing_map.get(external_id)
                fields = dict(
                    source=ListingSource.MANUAL.value,
                    title=item.get("title") or "Untitled",
                    listing_type=n["listing_type"],
                    status=n["status"],
                    description=item.get("description"),
                    price=item.get("price"),
                    price_display=item.get("price_display"),
                    currency=n["currency"],
                    street=item.get("street"),
                    suburb=item.get("suburb"),
                    state=item.get("state"),
                    postcode=item.get("postcode"),
                    bedrooms=item.get("bedrooms"),
                    bathrooms=item.get("bathrooms"),
                    garages=item.get("garages"),
                    land_sqm=item.get("land_sqm"),
                    house_sqm=item.get("house_sqm"),
                    has_pool=bool(item.get("has_pool", False)),
                    raw_data=item.get("raw_data", {}),
                )
                try:
                    if existing:
                        for key, value in fields.items():
                            if value is not None:
                                setattr(existing, key, value)
                        upserted_listings.append(existing)
                    else:
                        listing, _ = await repo.upsert_listing(
                            db,
                            tenant_id=tenant_id,
                            external_id=external_id,
                            public_id=_new_public_id(),
                            **fields,
                        )
                        upserted_listings.append(listing)
                    processed += 1
                except Exception as exc:
                    logger.error(
                        f"ListingUploadJob {job_id}: failed to upsert row {row_num}: {exc}"
                    )

            # ── 4d: ONE flush + commit for the entire batch ───────────────
            await db.flush()
            await db.commit()

            # ── 4e: Queue ONE batch embed task per batch (ids are stable) ──
            batch_listing_ids = [lst.id for lst in upserted_listings]
            embed_listings_batch.apply_async(
                kwargs=dict(listing_ids=batch_listing_ids, tenant_id=tenant_id),
                queue=QUEUEEnum.ANALYSIS.value,
            )

            await repo.update_listing_upload_job(db, job=job, processed_rows=processed)
            await db.commit()

        # ── Step 5: Finalize ──────────────────────────────────────────────
        await repo.update_listing_upload_job(
            db, job=job, status=UploadJobStatus.COMPLETED, processed_rows=processed
        )
        await db.commit()
        logger.info(
            f"ListingUploadJob {job_id}: completed. "
            f"processed={processed}/{total_rows}"
        )


def _get_listing_file_bytes(job: Any) -> bytes:
    """Retrieve raw file bytes from wherever they live. Blob now, S3/GCS later."""
    if job.file_data:
        return bytes(job.file_data)
    if job.storage_path:
        # TODO: swap in S3/GCS fetch when migrating off blob storage
        raise NotImplementedError(
            f"S3/GCS fetch not yet implemented. storage_path={job.storage_path}"
        )
    raise ValueError(
        f"ListingUploadJob {job.id} has neither file_data nor storage_path."
    )


# =============================================================================
# TASK G — RECOVER STUCK CRAWL JOBS
# =============================================================================


@celery_app.task(
    name="app.modules.chatbot.tasks.retry_stuck_crawl_jobs",
    queue=QUEUEEnum.ANALYSIS.value,
)
def retry_stuck_crawl_jobs() -> str:
    """
    Beat task — runs every 10 minutes.
    Finds crawl jobs stuck in 'queued' (≥5 min) or 'running' (≥30 min)
    and re-dispatches crawl_and_embed for each one.
    """
    return _run(_retry_stuck_crawl_jobs_async())


async def _retry_stuck_crawl_jobs_async() -> str:
    async with get_task_db_session() as db:
        stuck_jobs = await repo.get_stuck_crawl_jobs(db)

        if not stuck_jobs:
            logger.info("retry_stuck_crawl_jobs: no stuck jobs found.")
            return "no stuck jobs"

        requeued = 0
        for job in stuck_jobs:
            ks = job.knowledge_source
            if not ks:
                logger.warning(f"CrawlJob {job.id} has no knowledge_source — skipping.")
                continue

            # Reset to queued so the task starts clean
            await repo.update_crawl_job(
                db,
                job=job,
                status=CrawlStatus.QUEUED,
                started_at=None,
                error_message=None,
                pages_found=0,
                pages_processed=0,
                pages_failed=0,
            )
            await db.commit()

            crawl_and_embed.apply_async(
                kwargs=dict(
                    crawl_job_id=job.id,
                    tenant_id=job.tenant_id,
                    knowledge_source_id=job.knowledge_source_id,
                    chatbot_config_id=ks.chatbot_config_id,
                    base_url=job.base_url,
                ),
                queue=QUEUEEnum.ANALYSIS.value,
            )
            requeued += 1
            logger.info(
                f"retry_stuck_crawl_jobs: re-queued CrawlJob {job.id} (url={job.base_url!r})"
            )

        return f"requeued {requeued} stuck crawl jobs"


# =============================================================================
# TASK H — RETRY FAILED DOCUMENTS
# Scans all documents stuck in FAILED or PROCESSING state and re-queues them.
# Runs every 15 minutes via Celery Beat.
# =============================================================================


@celery_app.task(
    name="app.modules.chatbot.tasks.retry_failed_documents",
    queue=QUEUEEnum.ANALYSIS.value,
)
def retry_failed_documents() -> str:
    """
    Beat task — runs every 15 minutes.
    Finds documents stuck in FAILED or PROCESSING state (>10 min old)
    and re-dispatches the appropriate ingestion task.

    PROCESSING documents that are >10 min old are considered orphaned
    (the worker crashed before finishing) and are safe to re-queue.
    """
    return _run(_retry_failed_documents_async())


async def _retry_failed_documents_async() -> str:
    import sentry_sdk
    from datetime import timedelta

    async with get_task_db_session() as db:
        stale_docs = await repo.get_stale_documents(
            db,
            failed_or_processing_older_than_minutes=10,
        )

        if not stale_docs:
            logger.info("retry_failed_documents: no stale documents found.")
            return "no stale documents"

        requeued = 0
        for doc in stale_docs:
            try:
                # Reset so the task starts clean
                await repo.update_document(
                    db,
                    doc=doc,
                    status=DocStatus.PENDING,
                    error_message=None,
                )
                await db.commit()

                process_document.apply_async(
                    kwargs=dict(
                        document_id=doc.id,
                        tenant_id=doc.tenant_id,
                        chatbot_config_id=doc.knowledge_source.chatbot_config_id,
                    ),
                    queue=QUEUEEnum.ANALYSIS.value,
                )
                requeued += 1
                logger.info(
                    "retry_failed_documents: re-queued Document %d (type=%s tenant=%d)",
                    doc.id, doc.file_type, doc.tenant_id,
                )
            except Exception as exc:
                sentry_sdk.capture_exception(exc)
                logger.error(
                    "retry_failed_documents: failed to re-queue Document %d: %s",
                    doc.id, exc,
                )

        return f"requeued {requeued} stale documents"


# =============================================================================
# LEGACY — live link scrapper (kept for backwards compat)
# =============================================================================

@celery_app.task(
    bind=True,
    name="app.modules.chatbot.tasks.live_link_scrapper",
    max_retries=settings.CELERY_MAX_TRIES,
    default_retry_delay=settings.CELERY_DEFAULT_RETRY_DELAY,
    queue=QUEUEEnum.ANALYSIS.value,
)
def live_link_scrapper(self, link: str) -> str:
    if not link:
        raise ValueError("No link provided")
    try:
        result = asyncio.run(website_parser.scrape_websites(link))
        logger.info(f"Scraping completed for link: {link}")
        return "Scraping completed successfully"
    except Exception as exc:
        countdown = 2 ** self.request.retries
        logger.error(f"Error scraping {link}, retrying in {countdown}s: {exc}")
        raise self.retry(exc=exc, countdown=countdown)