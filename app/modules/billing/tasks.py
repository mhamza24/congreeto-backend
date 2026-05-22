# app/modules/billing/tasks.py
"""
Celery tasks for billing.

Schedule:
    billing.reconcile_usage     → every hour
    billing.check_usage_limits  → every hour (after reconcile)
    billing.reset_monthly_usage → 1st of month at 00:05 UTC
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from celery import shared_task
from sqlalchemy import text

from app.core.database import SyncSessionLocal
from app.core.enums import UsageMetric, LimitStatus
from app.modules.billing.task_helpers import current_period_month, compute_limit_status

logger = logging.getLogger(__name__)

# Metrics to check limits for
CHECKED_METRICS = [
    (UsageMetric.CONVERSATIONS,      "max_conversations_per_month", 750),
    (UsageMetric.TOKENS_USED,        "max_tokens_per_month",        1_000_000),
    (UsageMetric.DOCUMENTS_UPLOADED, "max_documents",               120),
    (UsageMetric.PAGES_CRAWLED,      "max_pages_crawled",           50),
]


# =============================================================================
# REAL-TIME USAGE INCREMENT
# =============================================================================

@shared_task(
    name="billing.increment_usage",
    max_retries=3,
    default_retry_delay=5,
    acks_late=True,
)
def increment_usage_task(
    tenant_id: int,
    metric: str,
    amount: int = 1,
) -> None:
    """
    Fire-and-forget real-time increment.
    Called after: conversation started, message sent, document uploaded, page crawled.
    """
    period = current_period_month()
    try:
        with SyncSessionLocal() as db:
            db.execute(
                text("""
                    INSERT INTO usage_records
                        (tenant_id, metric, period_month, quantity, recorded_at)
                    VALUES
                        (:tenant_id, :metric, :period_month, :amount,
                         NOW() AT TIME ZONE 'UTC')
                    ON CONFLICT (tenant_id, metric, period_month)
                    DO UPDATE SET
                        quantity    = usage_records.quantity + :amount,
                        recorded_at = NOW() AT TIME ZONE 'UTC'
                """),
                {
                    "tenant_id":    tenant_id,
                    "metric":       metric,
                    "period_month": period,
                    "amount":       amount,
                }
            )
            db.commit()
    except Exception as exc:
        logger.exception(
            f"increment_usage_task failed tenant={tenant_id} metric={metric}"
        )
        raise increment_usage_task.retry(exc=exc)


# =============================================================================
# HOURLY RECONCILIATION
# =============================================================================

@shared_task(name="billing.reconcile_usage", max_retries=2)
def reconcile_usage_task() -> None:
    """
    Runs every hour.
    Cross-checks usage_records against actual DB counts.
    Fixes drift caused by failed real-time increments.
    """
    period = current_period_month()
    logger.info(f"Starting usage reconciliation period={period}")

    with SyncSessionLocal() as db:

        # Conversations — count new sessions this month
        db.execute(text("""
            INSERT INTO usage_records
                (tenant_id, metric, period_month, quantity, recorded_at)
            SELECT
                tenant_id::bigint,
                'conversations',
                :period,
                COUNT(*),
                NOW() AT TIME ZONE 'UTC'
            FROM conversations
            WHERE DATE_TRUNC('month', created_at AT TIME ZONE 'UTC')
                = DATE_TRUNC('month', NOW() AT TIME ZONE 'UTC')
            GROUP BY tenant_id
            ON CONFLICT (tenant_id, metric, period_month)
            DO UPDATE SET
                quantity    = EXCLUDED.quantity,
                recorded_at = NOW() AT TIME ZONE 'UTC'
        """), {"period": period})

        # Messages — join through conversations to get tenant_id
        db.execute(text("""
            INSERT INTO usage_records
                (tenant_id, metric, period_month, quantity, recorded_at)
            SELECT
                c.tenant_id::bigint,
                'messages',
                :period,
                COUNT(*),
                NOW() AT TIME ZONE 'UTC'
            FROM messages m
            JOIN conversations c ON c.id = m.conversation_id
            WHERE DATE_TRUNC('month', m.created_at AT TIME ZONE 'UTC')
                = DATE_TRUNC('month', NOW() AT TIME ZONE 'UTC')
            GROUP BY c.tenant_id
            ON CONFLICT (tenant_id, metric, period_month)
            DO UPDATE SET
                quantity    = EXCLUDED.quantity,
                recorded_at = NOW() AT TIME ZONE 'UTC'
        """), {"period": period})

        # Tokens — join through conversations to get tenant_id
        db.execute(text("""
            INSERT INTO usage_records
                (tenant_id, metric, period_month, quantity, recorded_at)
            SELECT
                c.tenant_id::bigint,
                'tokens_used',
                :period,
                COALESCE(SUM(m.tokens_used), 0),
                NOW() AT TIME ZONE 'UTC'
            FROM messages m
            JOIN conversations c ON c.id = m.conversation_id
            WHERE DATE_TRUNC('month', m.created_at AT TIME ZONE 'UTC')
                = DATE_TRUNC('month', NOW() AT TIME ZONE 'UTC')
            AND m.tokens_used IS NOT NULL
            GROUP BY c.tenant_id
            ON CONFLICT (tenant_id, metric, period_month)
            DO UPDATE SET
                quantity    = EXCLUDED.quantity,
                recorded_at = NOW() AT TIME ZONE 'UTC'
        """), {"period": period})

        # Active users — seat count
        db.execute(text("""
            INSERT INTO usage_records
                (tenant_id, metric, period_month, quantity, recorded_at)
            SELECT
                tenant_id::bigint,
                'active_users',
                :period,
                COUNT(*),
                NOW() AT TIME ZONE 'UTC'
            FROM tenant_users
            WHERE status = 'active'
            GROUP BY tenant_id
            ON CONFLICT (tenant_id, metric, period_month)
            DO UPDATE SET
                quantity    = EXCLUDED.quantity,
                recorded_at = NOW() AT TIME ZONE 'UTC'
        """), {"period": period})

        db.commit()

    logger.info("Usage reconciliation complete")


# =============================================================================
# HOURLY LIMIT CHECK + WARNING NOTIFICATIONS
# =============================================================================

@shared_task(name="billing.check_usage_limits", max_retries=2)
def check_usage_limits_task() -> None:
    """
    Runs every hour after reconciliation.
    Sends warnings at 80% and 90%.
    Logs hard blocks at 100% for admin review.
    """
    period = current_period_month()
    logger.info(f"Starting limit checks period={period}")

    with SyncSessionLocal() as db:

        # Get all active tenants
        tenants = db.execute(text("""
            SELECT DISTINCT ts.tenant_id
            FROM tenant_subscriptions ts
            WHERE ts.status IN ('active', 'trialing')
        """)).fetchall()

        for (tenant_id,) in tenants:
            # Get plan limits
            plan_row = db.execute(text("""
                SELECT p.limits
                FROM tenant_subscriptions ts
                JOIN plans p ON p.id = ts.plan_id
                WHERE ts.tenant_id = :tid
                AND ts.status IN ('active', 'trialing')
                ORDER BY ts.created_at DESC
                LIMIT 1
            """), {"tid": tenant_id}).one_or_none()

            if not plan_row:
                continue

            import json
            limits = (
                plan_row.limits
                if isinstance(plan_row.limits, dict)
                else json.loads(plan_row.limits)
            )

            for metric, limit_key, default in CHECKED_METRICS:
                try:
                    record = db.execute(text("""
                        SELECT quantity, warned_80, warned_90
                        FROM usage_records
                        WHERE tenant_id    = :tid
                        AND   metric       = :metric
                        AND   period_month = :period
                    """), {
                        "tid":    tenant_id,
                        "metric": metric.value,
                        "period": period,
                    }).one_or_none()

                    if not record:
                        continue

                    used      = record.quantity
                    warned_80 = record.warned_80
                    warned_90 = record.warned_90
                    limit     = int(limits.get(limit_key, default))

                    if limit <= 0:
                        continue

                    status = compute_limit_status(used, limit)

                    # ── Hard block ─────────────────────────────────────────
                    if status == LimitStatus.EXCEEDED:
                        logger.warning(
                            f"HARD BLOCK tenant={tenant_id} "
                            f"metric={metric.value} used={used}/{limit}"
                        )
                        # TODO: notify admin
                        # TODO: await email_service.send_limit_exceeded(tenant_id, metric, used, limit)

                    # ── 90% critical warning ───────────────────────────────
                    elif status == LimitStatus.CRITICAL and not warned_90:
                        logger.warning(
                            f"90% WARNING tenant={tenant_id} "
                            f"metric={metric.value} used={used}/{limit}"
                        )
                        db.execute(text("""
                            UPDATE usage_records
                            SET warned_90 = TRUE
                            WHERE tenant_id    = :tid
                            AND   metric       = :metric
                            AND   period_month = :period
                        """), {
                            "tid":    tenant_id,
                            "metric": metric.value,
                            "period": period,
                        })
                        # TODO: await email_service.send_usage_warning(tenant_id, metric, 90, used, limit)

                    # ── 80% warning ────────────────────────────────────────
                    elif status == LimitStatus.WARNING and not warned_80:
                        logger.info(
                            f"80% WARNING tenant={tenant_id} "
                            f"metric={metric.value} used={used}/{limit}"
                        )
                        db.execute(text("""
                            UPDATE usage_records
                            SET warned_80 = TRUE
                            WHERE tenant_id    = :tid
                            AND   metric       = :metric
                            AND   period_month = :period
                        """), {
                            "tid":    tenant_id,
                            "metric": metric.value,
                            "period": period,
                        })
                        # TODO: await email_service.send_usage_warning(tenant_id, metric, 80, used, limit)

                except Exception:
                    logger.exception(
                        f"Limit check failed tenant={tenant_id} metric={metric.value}"
                    )

        db.commit()

    logger.info("Limit checks complete")


# =============================================================================
# MONTHLY RESET
# =============================================================================

@shared_task(name="billing.reset_monthly_usage", max_retries=2)
def reset_monthly_usage_task() -> None:
    """
    Runs on 1st of each month at 00:05 UTC.
    Old usage_records are kept for history — new month starts fresh
    because period_month is part of the unique key.
    This task renews subscription periods and resets warning flags.
    """
    now    = datetime.now(timezone.utc)
    period = now.strftime("%Y-%m")
    logger.info(f"Monthly reset started new period={period}")

    with SyncSessionLocal() as db:

        # Renew tenant subscription periods
        db.execute(text("""
            UPDATE tenant_subscriptions
            SET
                current_period_start = NOW() AT TIME ZONE 'UTC',
                current_period_end   = NOW() AT TIME ZONE 'UTC'
                                       + INTERVAL '30 days'
            WHERE status IN ('active', 'trialing')
        """))

        # Renew user subscription periods (manually-activated plans not managed by Stripe)
        db.execute(text("""
            UPDATE user_subscriptions
            SET
                current_period_start = NOW() AT TIME ZONE 'UTC',
                current_period_end   = NOW() AT TIME ZONE 'UTC'
                                       + INTERVAL '30 days'
            WHERE status IN ('active', 'trialing')
            AND   stripe_subscription_id IS NULL
        """))

        db.commit()

    logger.info("Monthly reset complete")