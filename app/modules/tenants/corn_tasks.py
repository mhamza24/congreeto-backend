# app/modules/tenants/corn_tasks.py
"""
Periodic Celery tasks for tenant lifecycle management.

Schedule (register in celery_worker.py beat_schedule):
    tenants.expire_trials        → every hour  (crontab(minute=0))
    tenants.sync_past_due_tenants → every hour  (crontab(minute=30))
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from celery import shared_task
from sqlalchemy import text

from app.core.database import SyncSessionLocal

logger = logging.getLogger(__name__)


# =============================================================================
# TRIAL EXPIRY
# =============================================================================

@shared_task(name="tenants.expire_trials", max_retries=2)
def expire_trials_task() -> None:
    """
    Runs every hour.

    Two sub-jobs:
      1. trial → active
         Tenants whose trial_ends_at has passed AND who have an active/trialing
         subscription get promoted to 'active'.  This is the happy path —
         the tenant already has a subscription, they just need to move off trial.

      2. trial → suspended
         Tenants whose trial_ends_at has passed AND who have NO active
         subscription (never paid) get suspended.  The frontend will gate them
         to the paywall on their next login.

    Also mirrors the change to the tenant_subscriptions table:
      trialing → active  (case 1)
      trialing → cancelled  (case 2, no payment on file)
    """
    now = datetime.now(timezone.utc)
    logger.info(f"expire_trials_task started at={now.isoformat()}")

    with SyncSessionLocal() as db:

        # ── Case 1: trial → active (subscription exists and is trialing) ─────
        promoted = db.execute(text("""
            UPDATE tenants t
            SET
                status     = 'active',
                updated_at = NOW() AT TIME ZONE 'UTC'
            FROM tenant_subscriptions ts
            WHERE
                t.id            = ts.tenant_id
                AND t.status    = 'trial'
                AND t.trial_ends_at <= NOW() AT TIME ZONE 'UTC'
                AND ts.status   = 'trialing'
                AND t.deleted_at IS NULL
            RETURNING t.id
        """)).rowcount
        logger.info(f"expire_trials_task: promoted {promoted} tenants trial→active")

        # Mirror on subscription side: trialing → active
        db.execute(text("""
            UPDATE tenant_subscriptions ts
            SET
                status     = 'active',
                updated_at = NOW() AT TIME ZONE 'UTC'
            FROM tenants t
            WHERE
                ts.tenant_id  = t.id
                AND t.status  = 'active'
                AND ts.status = 'trialing'
                AND ts.trial_ends_at <= NOW() AT TIME ZONE 'UTC'
        """))

        # ── Case 2: trial → suspended (no paid subscription) ─────────────────
        suspended = db.execute(text("""
            UPDATE tenants t
            SET
                status     = 'suspended',
                updated_at = NOW() AT TIME ZONE 'UTC'
            WHERE
                t.status        = 'trial'
                AND t.trial_ends_at <= NOW() AT TIME ZONE 'UTC'
                AND t.deleted_at IS NULL
                AND NOT EXISTS (
                    SELECT 1
                    FROM tenant_subscriptions ts
                    WHERE
                        ts.tenant_id = t.id
                        AND ts.status IN ('trialing', 'active', 'past_due')
                )
            RETURNING t.id
        """)).rowcount
        logger.info(f"expire_trials_task: suspended {suspended} tenants trial→suspended (no subscription)")

        db.commit()

    logger.info("expire_trials_task complete")


# =============================================================================
# PAST-DUE GRACE PERIOD ENFORCEMENT
# =============================================================================

@shared_task(name="tenants.sync_past_due_tenants", max_retries=2)
def sync_past_due_tenants_task() -> None:
    """
    Runs every hour.

    Finds subscriptions that have been past_due for more than the grace period
    (default: 7 days) and cancels them, setting tenant.status = 'suspended'.

    When Stripe is live this logic moves to the Stripe webhook handler
    (subscription.deleted event). Until then this task acts as the fallback.

    Grace period is defined as: current_period_end + 7 days.
    If no current_period_end is set, falls back to updated_at + 7 days.
    """
    logger.info("sync_past_due_tenants_task started")

    with SyncSessionLocal() as db:
        cancelled = db.execute(text("""
            UPDATE tenant_subscriptions ts
            SET
                status       = 'cancelled',
                cancelled_at = NOW() AT TIME ZONE 'UTC',
                updated_at   = NOW() AT TIME ZONE 'UTC'
            WHERE
                ts.status = 'past_due'
                AND COALESCE(ts.current_period_end, ts.updated_at)
                    < NOW() AT TIME ZONE 'UTC' - INTERVAL '7 days'
            RETURNING ts.tenant_id
        """)).rowcount
        logger.info(f"sync_past_due_tenants_task: cancelled {cancelled} past-due subscriptions")

        # Suspend the corresponding tenants
        if cancelled > 0:
            db.execute(text("""
                UPDATE tenants t
                SET
                    status     = 'suspended',
                    updated_at = NOW() AT TIME ZONE 'UTC'
                WHERE
                    t.status != 'cancelled'
                    AND t.deleted_at IS NULL
                    AND NOT EXISTS (
                        SELECT 1
                        FROM tenant_subscriptions ts
                        WHERE
                            ts.tenant_id = t.id
                            AND ts.status IN ('trialing', 'active', 'past_due')
                    )
            """))

        db.commit()

    logger.info("sync_past_due_tenants_task complete")
