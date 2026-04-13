# app/modules/billing/task_helpers.py
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.billing import repository as repo
from app.core.enums import UsageMetric, LimitStatus

logger = logging.getLogger(__name__)


def current_period_month() -> str:
    """Returns current billing period as YYYY-MM."""
    return datetime.now(timezone.utc).strftime("%Y-%m")


def compute_limit_status(used: int, limit: int) -> LimitStatus:
    """
    ok       → < 80%
    warning  → 80–89%
    critical → 90–99%
    exceeded → 100%+  (hard block new sessions, current session continues)
    """
    if limit <= 0:
        return LimitStatus.EXCEEDED

    pct = (used / limit) * 100

    if pct >= 100:
        return LimitStatus.EXCEEDED
    if pct >= 90:
        return LimitStatus.CRITICAL
    if pct >= 80:
        return LimitStatus.WARNING
    return LimitStatus.OK


async def get_effective_limit(
    db: AsyncSession,
    *,
    tenant_id: int,
    metric_key: str,
    default: int = 0,
) -> int:
    """
    effective_limit = plan.limits[metric_key] + SUM(addon grants for metric_key)
    Returns default if tenant has no active subscription.
    """
    sub = await repo.get_active_subscription(db, tenant_id=tenant_id)
    if not sub:
        return default

    base_limit  = sub.plan.get_limit(metric_key, default)
    addon_grant = await repo.get_addon_grant_total(
        db, tenant_id=tenant_id, metric=metric_key
    )
    return base_limit + addon_grant


async def check_and_enforce_limit(
    db: AsyncSession,
    *,
    tenant_id: int,
    metric: UsageMetric,
    metric_key: str,
    default_limit: int = 0,
) -> tuple[int, int, LimitStatus]:
    """
    Returns (current_usage, effective_limit, limit_status).
    Callers use limit_status to decide whether to block.
    """
    period = current_period_month()
    record = await repo.get_usage(
        db, tenant_id=tenant_id, metric=metric, period_month=period
    )
    used   = record.quantity if record else 0
    limit  = await get_effective_limit(
        db, tenant_id=tenant_id, metric_key=metric_key, default=default_limit
    )
    status = compute_limit_status(used, limit)
    return used, limit, status


async def can_start_new_conversation(
    db: AsyncSession,
    *,
    tenant_id: int,
) -> tuple[bool, int, int, LimitStatus]:
    """
    Core check before creating a new conversation session.
    Returns (allowed, used, limit, status).
    allowed=False when status=EXCEEDED → block new session.
    allowed=True for all other statuses → session can start.
    """
    used, limit, status = await check_and_enforce_limit(
        db,
        tenant_id=tenant_id,
        metric=UsageMetric.CONVERSATIONS,
        metric_key="max_conversations_per_month",
        default_limit=750,
    )
    allowed = status != LimitStatus.EXCEEDED
    if not allowed:
        logger.warning("[billing] can_start_new_conversation blocked tenant=%d used=%d limit=%d", tenant_id, used, limit)
    else:
        logger.debug("[billing] can_start_new_conversation allowed tenant=%d used=%d limit=%d status=%s", tenant_id, used, limit, status)
    return allowed, used, limit, status


async def can_continue_conversation(
    db: AsyncSession,
    *,
    tenant_id: int,
    current_tokens_used: int,
) -> tuple[bool, int, int, LimitStatus]:
    """
    Check before processing each message in an existing conversation.
    Blocks if monthly token limit is exceeded.
    """
    used, limit, status = await check_and_enforce_limit(
        db,
        tenant_id=tenant_id,
        metric=UsageMetric.TOKENS_USED,
        metric_key="max_tokens_per_month",
        default_limit=1_000_000,
    )
    allowed = status != LimitStatus.EXCEEDED
    if not allowed:
        logger.warning("[billing] can_continue_conversation blocked tenant=%d used=%d limit=%d", tenant_id, used, limit)
    return allowed, used, limit, status


async def increment_and_check(
    db: AsyncSession,
    *,
    tenant_id: int,
    metric: UsageMetric,
    metric_key: str,
    amount: int = 1,
    default_limit: int = 0,
) -> tuple[int, int, LimitStatus]:
    """
    Increments usage then returns (used, limit, status).
    Used by real-time event handlers after each conversation/message.
    """
    period = current_period_month()
    await repo.increment_usage(
        db,
        tenant_id=tenant_id,
        metric=metric,
        period_month=period,
        amount=amount,
    )
    return await check_and_enforce_limit(
        db,
        tenant_id=tenant_id,
        metric=metric,
        metric_key=metric_key,
        default_limit=default_limit,
    )