from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text


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
