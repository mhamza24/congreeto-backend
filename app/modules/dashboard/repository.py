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
        -- rest of CTEs unchanged ...
        response_time AS (
            SELECT
                CONCAT(
                    FLOOR(AVG(m.response_ms) / 60000)::int, 'm ',
                    FLOOR((AVG(m.response_ms) % 60000) / 1000)::int, 's'
                ) AS avg_response_time_formatted,
                ROUND(AVG(m.response_ms) / 1000.0, 2) AS avg_response_time_sec
            FROM messages m
            JOIN conversations c ON c.id = m.conversation_id
            WHERE c.tenant_id = :tenant_id   -- ← same param, used twice
              AND m.role = 'assistant'
              AND m.response_ms IS NOT NULL
        )
        SELECT ...
        FROM kpis k
        ...
    """)

    result = await db.execute(query, {"tenant_id": tenant_id})  # ← bound here
    row = result.mappings().first()

    if not row:
        return {}

    return dict(row)