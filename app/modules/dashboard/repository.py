import asyncio
import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.utils.date_time_helper import parse_datetime

logger = logging.getLogger(__name__)


async def get_dashboard_summary(
    db: AsyncSession,
    *,
    tenant_id: str,
) -> dict:
    query = text("""
        WITH base AS (
            SELECT
                c.id,
                c.is_lead,
                c.lead_name,
                c.lead_email,
                c.lead_phone,
                c.created_at,
                ci.lead_tier,
                ci.engagement_score
            FROM conversations c
            LEFT JOIN conversation_insights ci ON ci.conversation_id = c.id
            WHERE c.tenant_id = :tenant_id
        ),

        kpis AS (
            SELECT
                COUNT(DISTINCT id)                                                      AS total_interactions,
                COUNT(DISTINCT CASE WHEN lead_tier = 'hot'     THEN id END)             AS hot_leads,
                COUNT(DISTINCT CASE WHEN lead_tier = 'nurture' THEN id END)             AS nurture_leads,
                COUNT(DISTINCT CASE WHEN
                    lead_name  IS NOT NULL
                    AND lead_email IS NOT NULL
                    AND lead_phone IS NOT NULL THEN id END)                             AS total_conversions,
                ROUND(
                    COUNT(DISTINCT CASE WHEN
                        lead_name  IS NOT NULL
                        AND lead_email IS NOT NULL
                        AND lead_phone IS NOT NULL THEN id END)::numeric
                    / NULLIF(COUNT(DISTINCT id), 0) * 100, 2
                )                                                                       AS conversion_rate_pct
            FROM base
        ),

        weekly AS (
            SELECT JSON_AGG(
                JSON_BUILD_OBJECT(
                    'day',                day,
                    'total_interactions', total_interactions,
                    'leads_captured',     leads_captured
                ) ORDER BY day
            ) AS weekly_activity
            FROM (
                SELECT
                    DATE_TRUNC('day', created_at)                                       AS day,
                    COUNT(DISTINCT id)                                                  AS total_interactions,
                    COUNT(DISTINCT CASE WHEN is_lead = true THEN id END)                AS leads_captured
                FROM base
                WHERE created_at >= NOW() - INTERVAL '7 days'
                GROUP BY DATE_TRUNC('day', created_at)
            ) w
        ),

        funnel AS (
            SELECT JSON_BUILD_OBJECT(
                'total_interactions', COUNT(DISTINCT id),
                'hot_leads',          COUNT(DISTINCT CASE WHEN lead_tier = 'hot' THEN id END),
                'conversions',        COUNT(DISTINCT CASE WHEN
                                          lead_name  IS NOT NULL
                                          AND lead_email IS NOT NULL
                                          AND lead_phone IS NOT NULL THEN id END)
            ) AS lead_funnel
            FROM base
        ),

        response_time AS (
            SELECT
                CONCAT(
                    FLOOR(AVG(m.response_ms) / 60000)::int, 'm ',
                    FLOOR((AVG(m.response_ms) % 60000) / 1000)::int, 's'
                )                                                                       AS avg_response_time_formatted,
                ROUND(AVG(m.response_ms) / 1000.0, 2)                                  AS avg_response_time_sec
            FROM messages m
            JOIN conversations c ON c.id = m.conversation_id
            WHERE c.tenant_id = :tenant_id
              AND m.role = 'assistant'
              AND m.response_ms IS NOT NULL
        )

        SELECT
            k.total_interactions,
            k.hot_leads,
            k.nurture_leads,
            k.total_conversions,
            k.conversion_rate_pct,
            rt.avg_response_time_formatted,
            rt.avg_response_time_sec,
            w.weekly_activity,
            f.lead_funnel
        FROM kpis k
        CROSS JOIN weekly w
        CROSS JOIN funnel f
        CROSS JOIN response_time rt
    """)

    result = await db.execute(query, {"tenant_id": tenant_id})
    row = result.mappings().first()
    return dict(row) if row else {}


async def get_leads_paginated(
    db: AsyncSession,
    *,
    tenant_id: str,
    page: int = 1,
    page_size: int = 10,
) -> dict:
    offset = (page - 1) * page_size
    query = text("""
        WITH lead_data AS (
            SELECT
                c.public_id,
                c.is_lead,
                c.lead_name,
                c.lead_email,
                c.lead_phone,
                c.total_messages,
                c.summary,
                c.status,
                c.last_activity_at,
                c.created_at,
                ci.lead_tier,
                ci.lead_score,
                ci.sentiment,
                ci.engagement_score,
                ci.ai_summary,
                ci.industry,
                ci.industry_insights
            FROM conversations c
            LEFT JOIN conversation_insights ci ON ci.conversation_id = c.id
            WHERE c.tenant_id = :tenant_id
            ORDER BY c.created_at DESC
        ),
        total_count AS (
            SELECT COUNT(*) AS total FROM lead_data
        )
        SELECT
            ld.*,
            tc.total
        FROM lead_data ld
        CROSS JOIN total_count tc
        LIMIT :page_size OFFSET :offset
    """)

    result = await db.execute(
        query,
        {"tenant_id": tenant_id, "page_size": page_size, "offset": offset},
    )
    rows = result.mappings().all()
    total = rows[0]["total"] if rows else 0
    leads = [dict(r) for r in rows]
    for lead in leads:
        lead.pop("total", None)

    return {
        "leads": leads,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": -(-total // page_size),  # ceiling division
        },
    }


async def get_lead_detail(
    db: AsyncSession,
    *,
    tenant_id: str,
    public_id: str,
) -> Optional[dict]:
    query = text("""
        WITH message_stats AS (
            SELECT
                m.conversation_id,
                COUNT(*) FILTER (WHERE m.role = 'user')                             AS user_messages,
                COUNT(*) FILTER (WHERE m.role = 'assistant')                        AS assistant_messages,
                ROUND(AVG(m.response_ms) FILTER (WHERE m.role = 'assistant'), 2)    AS avg_response_ms,
                MIN(m.response_ms) FILTER (WHERE m.role = 'assistant')              AS min_response_ms,
                MAX(m.response_ms) FILTER (WHERE m.role = 'assistant')              AS max_response_ms,
                SUM(m.tokens_used)                                                  AS total_tokens_messages,
                MIN(m.created_at)                                                   AS first_message_at,
                MAX(m.created_at)                                                   AS last_message_at,
                EXTRACT(EPOCH FROM (MAX(m.created_at) - MIN(m.created_at)))         AS conversation_duration_sec
            FROM messages m
            GROUP BY m.conversation_id
        )
        SELECT
            c.public_id,
            c.is_lead,
            c.lead_name,
            c.lead_email,
            c.lead_phone,
            c.total_messages,
            c.total_tokens_used,
            c.summary,
            c.running_summary,
            c.status,
            c.page_url,
            c.last_activity_at,
            c.created_at,
            c.closed_at,
            ci.lead_score,
            ci.lead_tier,
            ci.industry,
            ci.industry_insights,
            ci.sentiment,
            ci.engagement_score,
            ci.topics_mentioned,
            ci.ai_summary,
            ci.ai_insights,
            ci.processed_at,
            ms.user_messages,
            ms.assistant_messages,
            ms.avg_response_ms,
            ms.min_response_ms,
            ms.max_response_ms,
            ms.total_tokens_messages,
            ms.first_message_at,
            ms.last_message_at,
            ms.conversation_duration_sec
        FROM conversations c
        LEFT JOIN conversation_insights ci ON ci.conversation_id = c.id
        LEFT JOIN message_stats ms ON ms.conversation_id = c.id
        WHERE c.tenant_id = :tenant_id
          AND c.public_id = :public_id
    """)

    result = await db.execute(query, {"tenant_id": tenant_id, "public_id": public_id})
    row = result.mappings().first()
    if not row:
        return None

    messages_query = text("""
        SELECT
            m.public_id,
            m.role,
            m.content,
            m.tokens_used,
            m.model_used,
            m.response_ms,
            m.created_at
        FROM messages m
        JOIN conversations c ON c.id = m.conversation_id
        WHERE c.tenant_id = :tenant_id
          AND c.public_id = :public_id
        ORDER BY m.created_at ASC
    """)

    msg_result = await db.execute(messages_query, {"tenant_id": tenant_id, "public_id": public_id})
    messages = [dict(r) for r in msg_result.mappings().all()]

    detail = dict(row)
    detail["messages"] = messages
    return detail


async def get_leads_for_export(
    db: AsyncSession,
    *,
    tenant_id: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    last_days: Optional[int] = None,
) -> list[dict]:
    date_from_parsed = parse_datetime(date_from) if date_from else None
    date_to_parsed   = parse_datetime(date_to)   if date_to   else None

    filters = "WHERE c.tenant_id = :tenant_id"
    params: dict = {"tenant_id": tenant_id}

    if last_days is not None:
        filters += f" AND c.created_at >= NOW() - INTERVAL '{int(last_days)} days'"
    elif date_from_parsed and date_to_parsed:
        filters += " AND c.created_at BETWEEN :date_from AND :date_to"
        params["date_from"] = date_from_parsed
        params["date_to"]   = date_to_parsed
    elif date_from_parsed:
        filters += " AND c.created_at >= :date_from"
        params["date_from"] = date_from_parsed
    elif date_to_parsed:
        filters += " AND c.created_at <= :date_to"
        params["date_to"] = date_to_parsed

    query = text(f"""
        SELECT
            c.public_id          AS conversation_id,
            c.is_lead,
            c.lead_name,
            c.lead_email,
            c.lead_phone,
            c.total_messages,
            c.status,
            c.summary,
            c.last_activity_at,
            c.created_at,
            ci.lead_tier,
            ci.lead_score,
            ci.industry,
            ci.industry_insights,
            ci.sentiment,
            ci.engagement_score,
            ci.topics_mentioned,
            ci.ai_summary
        FROM conversations c
        LEFT JOIN conversation_insights ci ON ci.conversation_id = c.id
        {filters}
        ORDER BY c.created_at DESC
    """)

    result = await db.execute(query, params)
    return [dict(r) for r in result.mappings().all()]


# =============================================================================
# SUPER-ADMIN — platform-wide analytics
# =============================================================================

async def get_admin_overview(db: AsyncSession) -> dict:
    """
    Single query that returns all platform-wide KPIs for the super-admin
    dashboard in one round-trip.
    """
    query = text("""
        WITH tenant_stats AS (
            SELECT
                COUNT(*)                                                            AS total,
                COUNT(*) FILTER (WHERE status = 'active'       AND deleted_at IS NULL) AS active,
                COUNT(*) FILTER (WHERE status = 'trial'        AND deleted_at IS NULL) AS trial,
                COUNT(*) FILTER (WHERE status = 'pending_plan' AND deleted_at IS NULL) AS pending_plan,
                COUNT(*) FILTER (WHERE status = 'suspended'    AND deleted_at IS NULL) AS suspended,
                COUNT(*) FILTER (WHERE status = 'cancelled'    AND deleted_at IS NULL) AS cancelled
            FROM tenants
            WHERE deleted_at IS NULL
        ),

        user_stats AS (
            SELECT COUNT(*) AS total_users
            FROM users
            WHERE deleted_at IS NULL
        ),

        conv_stats AS (
            SELECT
                COUNT(*)                                                            AS total_conversations,
                COUNT(*) FILTER (
                    WHERE created_at >= DATE_TRUNC('month', NOW() AT TIME ZONE 'UTC')
                )                                                                   AS conversations_this_month,
                COUNT(*) FILTER (WHERE status = 'in_progress')                     AS active_conversations
            FROM conversations
        ),

        lead_stats AS (
            SELECT
                COUNT(*) FILTER (WHERE lead_tier = 'hot')     AS hot,
                COUNT(*) FILTER (WHERE lead_tier = 'nurture') AS nurture,
                COUNT(*) FILTER (WHERE lead_tier = 'cold')    AS cold,
                COUNT(*)                                       AS total
            FROM conversation_insights
        ),

        revenue_stats AS (
            SELECT
                COALESCE(SUM(p.price_aud_cents) FILTER (WHERE ts.status = 'active'),    0) / 100.0 AS mrr_aud,
                COALESCE(SUM(p.price_aud_cents) FILTER (WHERE ts.status = 'trialing'),  0)         AS _trialing_cents,
                COUNT(*) FILTER (WHERE ts.status = 'active')   AS active_subscriptions,
                COUNT(*) FILTER (WHERE ts.status = 'trialing') AS trialing_subscriptions,
                COUNT(*) FILTER (WHERE ts.status = 'past_due') AS past_due_subscriptions
            FROM tenant_subscriptions ts
            JOIN plans p ON p.id = ts.plan_id
            WHERE ts.status IN ('active', 'trialing', 'past_due')
        ),

        plan_dist AS (
            SELECT JSON_AGG(
                JSON_BUILD_OBJECT(
                    'plan_name',        p.name,
                    'plan_slug',        p.slug,
                    'billing_interval', p.billing_interval,
                    'subscriber_count', sub_count,
                    'revenue_aud',      sub_revenue_aud
                ) ORDER BY sub_revenue_aud DESC
            ) AS plan_distribution
            FROM (
                SELECT
                    ts.plan_id,
                    COUNT(*)                                     AS sub_count,
                    SUM(p2.price_aud_cents) / 100.0              AS sub_revenue_aud
                FROM tenant_subscriptions ts
                JOIN plans p2 ON p2.id = ts.plan_id
                WHERE ts.status = 'active'
                GROUP BY ts.plan_id
            ) pd
            JOIN plans p ON p.id = pd.plan_id
        ),

        chatbot_stats AS (
            SELECT
                COUNT(*) FILTER (WHERE status = 'active')   AS active,
                COUNT(*) FILTER (WHERE status = 'draft')    AS draft,
                COUNT(*) FILTER (WHERE status = 'inactive') AS inactive
            FROM chatbot_configs
        ),

        daily_activity AS (
            SELECT JSON_AGG(
                JSON_BUILD_OBJECT(
                    'day',             TO_CHAR(day, 'YYYY-MM-DD'),
                    'conversations',   total_conversations,
                    'leads_captured',  leads_captured
                ) ORDER BY day
            ) AS daily_activity
            FROM (
                SELECT
                    DATE_TRUNC('day', created_at AT TIME ZONE 'UTC') AS day,
                    COUNT(*)                                          AS total_conversations,
                    COUNT(*) FILTER (WHERE is_lead = TRUE)           AS leads_captured
                FROM conversations
                WHERE created_at >= NOW() - INTERVAL '30 days'
                GROUP BY DATE_TRUNC('day', created_at AT TIME ZONE 'UTC')
            ) d
        )

        SELECT
            -- tenants
            t.total            AS tenant_total,
            t.active           AS tenant_active,
            t.trial            AS tenant_trial,
            t.pending_plan     AS tenant_pending_plan,
            t.suspended        AS tenant_suspended,
            t.cancelled        AS tenant_cancelled,
            -- users
            u.total_users,
            -- conversations
            c.total_conversations,
            c.conversations_this_month,
            c.active_conversations,
            -- leads
            l.hot              AS lead_hot,
            l.nurture          AS lead_nurture,
            l.cold             AS lead_cold,
            l.total            AS lead_total,
            -- revenue
            r.mrr_aud,
            r.mrr_aud * 12     AS arr_aud,
            r.active_subscriptions,
            r.trialing_subscriptions,
            r.past_due_subscriptions,
            pd.plan_distribution,
            -- chatbots
            cb.active          AS chatbot_active,
            cb.draft           AS chatbot_draft,
            cb.inactive        AS chatbot_inactive,
            -- activity
            da.daily_activity
        FROM tenant_stats t
        CROSS JOIN user_stats u
        CROSS JOIN conv_stats c
        CROSS JOIN lead_stats l
        CROSS JOIN revenue_stats r
        CROSS JOIN plan_dist pd
        CROSS JOIN chatbot_stats cb
        CROSS JOIN daily_activity da
    """)

    result = await db.execute(query)
    row = result.mappings().first()
    return dict(row) if row else {}


async def get_admin_tenants(
    db: AsyncSession,
    *,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """
    Paginated tenant table for the super-admin dashboard.
    Returns (rows, total_count).
    """
    rows_query = text("""
        SELECT
            t.public_id,
            t.name,
            t.slug,
            t.status,
            p.name                                              AS plan_name,
            ts.status                                           AS subscription_status,
            COALESCE(conv_counts.total_conversations, 0)        AS total_conversations,
            COALESCE(member_counts.member_count, 0)             AS member_count,
            TO_CHAR(t.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS created_at
        FROM tenants t
        LEFT JOIN tenant_subscriptions ts
               ON ts.tenant_id = t.id
              AND ts.status IN ('active', 'trialing', 'past_due')
        LEFT JOIN plans p ON p.id = ts.plan_id
        LEFT JOIN (
            SELECT tenant_id, COUNT(*) AS total_conversations
            FROM conversations
            GROUP BY tenant_id
        ) conv_counts ON conv_counts.tenant_id = t.slug
        LEFT JOIN (
            SELECT tenant_id, COUNT(*) AS member_count
            FROM tenant_users
            WHERE status = 'active'
            GROUP BY tenant_id
        ) member_counts ON member_counts.tenant_id = t.id
        WHERE t.deleted_at IS NULL
        ORDER BY t.created_at DESC
        LIMIT :limit OFFSET :offset
    """)

    count_query = text("""
        SELECT COUNT(*) FROM tenants WHERE deleted_at IS NULL
    """)

    rows_result, count_result = await asyncio.gather(
        db.execute(rows_query, {"limit": limit, "offset": offset}),
        db.execute(count_query),
    )

    rows = [dict(r) for r in rows_result.mappings().all()]
    total = count_result.scalar_one()
    return rows, total
