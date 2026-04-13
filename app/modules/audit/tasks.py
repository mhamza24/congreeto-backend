"""
app/modules/audit/tasks.py

Fire-and-forget Celery task for writing audit log entries from background workers
or high-frequency code paths where the DB session is not available inline.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from app.config.celery_worker import celery_app, QUEUEEnum
from app.core.database import get_task_db_session

logger = logging.getLogger(__name__)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        finally:
            loop.close()


@celery_app.task(
    name="app.modules.audit.tasks.write_audit_log",
    queue=QUEUEEnum.ANALYSIS.value,
    ignore_result=True,
)
def write_audit_log(
    *,
    entity_type: str,
    action: str,
    tenant_id: Optional[int] = None,
    user_id: Optional[int] = None,
    entity_id: Optional[int] = None,
    diff: Optional[dict] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> None:
    """
    Background task that writes one row to audit_logs.

    Usage (fire-and-forget from any sync context):
        from app.modules.audit import tasks as audit_tasks
        audit_tasks.write_audit_log.delay(
            tenant_id=...,
            user_id=...,
            entity_type="listings",
            entity_id=listing.id,
            action="create",
            diff={},
        )
    """
    _run(
        _write_audit_async(
            entity_type=entity_type,
            action=action,
            tenant_id=tenant_id,
            user_id=user_id,
            entity_id=entity_id,
            diff=diff,
            ip_address=ip_address,
            user_agent=user_agent,
        )
    )


async def _write_audit_async(
    *,
    entity_type: str,
    action: str,
    tenant_id: Optional[int],
    user_id: Optional[int],
    entity_id: Optional[int],
    diff: Optional[dict],
    ip_address: Optional[str],
    user_agent: Optional[str],
) -> None:
    from app.modules.audit import repository as audit

    async with get_task_db_session() as db:
        await audit.write(
            db,
            entity_type=entity_type,
            action=action,
            tenant_id=tenant_id,
            user_id=user_id,
            entity_id=entity_id,
            diff=diff,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await db.commit()
        logger.debug(
            "audit(bg): %s %s:%s tenant=%s user=%s",
            action, entity_type, entity_id, tenant_id, user_id,
        )
