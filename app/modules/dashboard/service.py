from __future__ import annotations
from fastapi import status
import json
import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import http_exception_handler
from app.modules.open_ai import service as openai_service
from app.modules.chat import tasks as background_tasks


from . import repository as repo
from . import schemas


logger = logging.getLogger(__name__)


async def fetch_summary(
    db: AsyncSession,
    *,
    tenant_id: str,
) -> schemas.DashboardSummaryResponse:
    logger.debug("[dashboard] fetch_summary tenant=%s", tenant_id)
    summary = await repo.get_dashboard_summary(db, tenant_id=tenant_id)
    logger.debug("[dashboard] fetch_summary complete tenant=%s", tenant_id)
    return schemas.DashboardSummaryResponse(summary=summary)


async def fetch_admin_overview(db: AsyncSession) -> schemas.AdminOverviewResponse:
    logger.debug("[dashboard] fetch_admin_overview")
    row = await repo.get_admin_overview(db)

    plan_dist = [
        schemas.PlanDistribution(**p)
        for p in (row.get("plan_distribution") or [])
    ]

    daily = [
        schemas.DailyActivity(**d)
        for d in (row.get("daily_activity") or [])
    ]

    return schemas.AdminOverviewResponse(
        tenants=schemas.TenantStatusBreakdown(
            total=row.get("tenant_total", 0),
            active=row.get("tenant_active", 0),
            trial=row.get("tenant_trial", 0),
            pending_plan=row.get("tenant_pending_plan", 0),
            suspended=row.get("tenant_suspended", 0),
            cancelled=row.get("tenant_cancelled", 0),
        ),
        total_users=row.get("total_users", 0),
        total_conversations=row.get("total_conversations", 0),
        conversations_this_month=row.get("conversations_this_month", 0),
        active_conversations=row.get("active_conversations", 0),
        leads=schemas.LeadBreakdown(
            hot=row.get("lead_hot", 0),
            nurture=row.get("lead_nurture", 0),
            cold=row.get("lead_cold", 0),
            total=row.get("lead_total", 0),
        ),
        revenue=schemas.RevenueMetrics(
            mrr_aud=float(row.get("mrr_aud", 0)),
            arr_aud=float(row.get("arr_aud", 0)),
            active_subscriptions=row.get("active_subscriptions", 0),
            trialing_subscriptions=row.get("trialing_subscriptions", 0),
            past_due_subscriptions=row.get("past_due_subscriptions", 0),
            plan_distribution=plan_dist,
        ),
        chatbots=schemas.ChatbotStats(
            active=row.get("chatbot_active", 0),
            draft=row.get("chatbot_draft", 0),
            inactive=row.get("chatbot_inactive", 0),
        ),
        daily_activity=daily,
    )


async def fetch_admin_tenants(
    db: AsyncSession,
    *,
    limit: int,
    offset: int,
) -> schemas.AdminTenantsResponse:
    logger.debug("[dashboard] fetch_admin_tenants limit=%s offset=%s", limit, offset)
    rows, total = await repo.get_admin_tenants(db, limit=limit, offset=offset)
    return schemas.AdminTenantsResponse(
        tenants=[schemas.TenantRow(**r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
