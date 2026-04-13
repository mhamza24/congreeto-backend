import asyncio
import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

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
                ci.budget_min,
                ci.budget_max,
                ci.suburbs_mentioned,
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
                )                                                                       AS conversion_rate_pct,
                ROUND(AVG(
                    CASE
                        WHEN budget_min IS NOT NULL AND budget_max IS NOT NULL
                            THEN (budget_min + budget_max) / 2.0
                        WHEN budget_min IS NOT NULL
                            THEN budget_min
                    END
                ))                                                                      AS avg_budget_aud
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

        budget_dist AS (
            SELECT JSON_AGG(
                JSON_BUILD_OBJECT(
                    'range',      budget_range,
                    'count',      count,
                    'percentage', percentage
                ) ORDER BY min_val
            ) AS budget_distribution
            FROM (
                SELECT
                    CASE
                        WHEN midpoint < 500000                     THEN '<$500K'
                        WHEN midpoint BETWEEN 500000 AND 799999    THEN '$500K–$800K'
                        WHEN midpoint BETWEEN 800000 AND 1199999   THEN '$800K–$1.2M'
                        WHEN midpoint >= 1200000                   THEN '$1.2M+'
                    END                                                                 AS budget_range,
                    MIN(midpoint)                                                       AS min_val,
                    COUNT(*)                                                            AS count,
                    ROUND(COUNT(*)::numeric / NULLIF(SUM(COUNT(*)) OVER (), 0) * 100, 2) AS percentage
                FROM (
                    SELECT
                        CASE
                            WHEN budget_min IS NOT NULL AND budget_max IS NOT NULL
                                THEN (budget_min + budget_max) / 2.0
                            WHEN budget_min IS NOT NULL
                                THEN budget_min::numeric
                        END AS midpoint
                    FROM base
                    WHERE budget_min IS NOT NULL OR budget_max IS NOT NULL
                ) mp
                WHERE midpoint IS NOT NULL
                GROUP BY budget_range
            ) bd
        ),

        suburb_heat AS (
            SELECT JSON_AGG(
                JSON_BUILD_OBJECT(
                    'suburb',     suburb,
                    'lead_count', lead_count
                ) ORDER BY lead_count DESC
            ) AS suburb_heatmap
            FROM (
                SELECT
                    UNNEST(suburbs_mentioned)                                           AS suburb,
                    COUNT(DISTINCT id)                                                  AS lead_count
                FROM base
                WHERE suburbs_mentioned IS NOT NULL
                GROUP BY UNNEST(suburbs_mentioned)
                ORDER BY lead_count DESC
                LIMIT 20
            ) sh
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
            k.avg_budget_aud,
            rt.avg_response_time_formatted,
            rt.avg_response_time_sec,
            w.weekly_activity,
            f.lead_funnel,
            b.budget_distribution,
            sh.suburb_heatmap
        FROM kpis k
        CROSS JOIN weekly w
        CROSS JOIN funnel f
        CROSS JOIN budget_dist b
        CROSS JOIN suburb_heat sh
        CROSS JOIN response_time rt
    """)

    result = await db.execute(query, {"tenant_id": tenant_id})
    row = result.mappings().first()
    return dict(row) if row else {}


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
