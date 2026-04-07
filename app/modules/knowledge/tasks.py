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
from app.core.database import AsyncSessionLocal
from app.modules.knowledge import repository as repo
from app.modules.knowledge.models import DocumentChunk
from app.modules.knowledge.parsers import website_parser
from app.modules.knowledge.parsers.pdf_parser import _parse_pdf
from app.modules.knowledge.task_helpers import (
    chunk_pages,
    chunk_plain_text,
    embed_chunks,
)
from app.core.enums import CrawlStatus, DocStatus

settings = get_settings()
logger = logging.getLogger(__name__)


# =============================================================================
# HELPERS
# =============================================================================

def _run(coro):
    """Run an async coroutine from a sync Celery task."""
    return asyncio.run(coro)


async def _flip_rag_if_needed(
    db: AsyncSession, *, tenant_id: int, chatbot_config_id: int
) -> None:
    """Flip rag_enabled on the chatbot once the first chunks exist."""
    await repo.flip_rag_enabled(
        db, tenant_id=tenant_id, chatbot_id=chatbot_config_id
    )
    await db.commit()


# =============================================================================
# TASK A — CRAWL WEBSITES + EMBED
# =============================================================================

@celery_app.task(
    bind=True,
    name="app.modules.knowledge.tasks.crawl_and_embed",
    max_retries=settings.CELERY_MAX_TRIES,
    default_retry_delay=settings.CELERY_DEFAULT_RETRY_DELAY,
    queue=QUEUEEnum.INGESTION.value,
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
    1. Mark crawl_job → running
    2. Scrape all pages under base_url
    3. For each page: create document row → chunk → embed → write chunks
    4. Mark crawl_job → completed (or failed)
    5. Flip rag_enabled if needed
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
        return f"crawl_and_embed completed for job_id={crawl_job_id}"

    except Exception as exc:
        countdown = 2 ** self.request.retries
        logger.error(
            f"crawl_and_embed failed for job_id={crawl_job_id}: {exc}. "
            f"Retrying in {countdown}s."
        )
        raise self.retry(exc=exc, countdown=countdown)


async def _crawl_and_embed_async(
    *,
    crawl_job_id: int,
    tenant_id: int,
    knowledge_source_id: int,
    chatbot_config_id: int,
    base_url: str,
) -> None:
    from app.modules.open_ai import service as openai_service

    async with AsyncSessionLocal() as db:
        # ── Step 1: Mark job running ──────────────────────────────────────
        job = await repo.get_crawl_job(db, tenant_id=tenant_id, job_id=crawl_job_id)
        if not job:
            logger.error(f"CrawlJob {crawl_job_id} not found.")
            return

        await repo.update_crawl_job(
            db,
            job=job,
            status=CrawlStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
        )
        await db.commit()

        # ── Step 2: Scrape ────────────────────────────────────────────────
        try:
            scraped: dict = await website_parser.scrape_websites(base_url)
        except Exception as exc:
            await repo.update_crawl_job(
                db,
                job=job,
                status=CrawlStatus.FAILED,
                error_message=str(exc),
                completed_at=datetime.now(timezone.utc),
            )
            await db.commit()
            raise

        # scraped = { base_url: { page_url: page_text, ... } }
        pages_dict: dict = scraped.get(base_url, {})
        pages_found = len(pages_dict)

        await repo.update_crawl_job(db, job=job, pages_found=pages_found)
        await db.commit()

        # ── Step 3: Process each page ─────────────────────────────────────
        pages_processed = 0
        pages_failed = 0

        for page_url, page_text in pages_dict.items():
            try:
                # Create document row for this page
                import uuid
                doc = await repo.create_document(
                    db,
                    knowledge_source_id=knowledge_source_id,
                    tenant_id=tenant_id,
                    file_name=page_url,
                    file_type="html",
                    file_size_bytes=len(page_text.encode()),
                    public_id=uuid.uuid4().hex,
                )
                await db.commit()

                # Chunk the page text
                raw_chunks = chunk_plain_text(page_text, source_url=page_url)

                if not raw_chunks:
                    await repo.update_document(
                        db, doc=doc,
                        status=DocStatus.READY,
                        chunk_count=0,
                    )
                    await db.commit()
                    pages_processed += 1
                    continue

                # Embed all chunks
                embedded_chunks = await embed_chunks(raw_chunks, openai_service)

                # Write DocumentChunk rows
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

                pages_processed += 1

            except Exception as exc:
                logger.error(f"Failed to process page {page_url}: {exc}")
                pages_failed += 1

        # ── Step 4: Finalize crawl job ────────────────────────────────────
        final_status = (
            CrawlStatus.COMPLETED if pages_failed == 0 else CrawlStatus.FAILED
        )
        await repo.update_crawl_job(
            db,
            job=job,
            status=final_status,
            pages_processed=pages_processed,
            pages_failed=pages_failed,
            completed_at=datetime.now(timezone.utc),
        )
        await db.commit()

        # ── Step 5: Flip rag_enabled ──────────────────────────────────────
        if pages_processed > 0:
            await _flip_rag_if_needed(
                db, tenant_id=tenant_id, chatbot_config_id=chatbot_config_id
            )

        logger.info(
            f"CrawlJob {crawl_job_id} done. "
            f"processed={pages_processed} failed={pages_failed}"
        )


# =============================================================================
# TASK B — PROCESS PDF DOCUMENT + EMBED
# =============================================================================

@celery_app.task(
    bind=True,
    name="app.modules.knowledge.tasks.process_document",
    max_retries=settings.CELERY_MAX_TRIES,
    default_retry_delay=settings.CELERY_DEFAULT_RETRY_DELAY,
    queue=QUEUEEnum.INGESTION.value,
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

    async with AsyncSessionLocal() as db:
        # ── Step 1: Fetch document ────────────────────────────────────────
        doc = await repo.get_document(db, tenant_id=tenant_id, document_id=document_id)
        if not doc:
            logger.error(f"Document {document_id} not found.")
            return

        await repo.update_document(db, doc=doc, status=DocStatus.PROCESSING)
        await db.commit()

        # ── Step 2: Get PDF bytes ─────────────────────────────────────────
        try:
            pdf_bytes = await _get_pdf_bytes(doc)
        except Exception as exc:
            await repo.update_document(
                db, doc=doc,
                status=DocStatus.FAILED,
                error_message=f"Could not fetch file: {exc}",
            )
            await db.commit()
            raise

        # ── Step 3: Parse PDF ─────────────────────────────────────────────
        try:
            parsed = _parse_pdf(pdf_bytes, extract_tables=True, password=None)
        except Exception as exc:
            await repo.update_document(
                db, doc=doc,
                status=DocStatus.FAILED,
                error_message=f"PDF parse error: {exc}",
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
# LEGACY — live link scrapper (kept for backwards compat)
# =============================================================================

@celery_app.task(
    bind=True,
    name="app.modules.knowledge.tasks.live_link_scrapper",
    max_retries=settings.CELERY_MAX_TRIES,
    default_retry_delay=settings.CELERY_DEFAULT_RETRY_DELAY,
    queue=QUEUEEnum.INGESTION.value,
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