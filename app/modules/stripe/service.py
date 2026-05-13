"""
Stripe integration service.

Three jobs:
  1. Create a Checkout Session  → tenant pays, Stripe redirects them back.
  2. Create a Customer Portal session → tenant manages cards/invoices/cancels.
  3. Dispatch incoming webhook events to the existing billing contracts —
     the actual subscription state changes still live in app.modules.billing,
     this module just translates Stripe events into those calls.

Idempotency
───────────
Stripe retries webhook delivery on any non-2xx response. We dedupe by
event id in Redis so a replay never double-applies a state change.

Webhook signature verification
──────────────────────────────
`stripe.Webhook.construct_event` verifies the `Stripe-Signature` header
against `STRIPE_WEBHOOK_SECRET`. Reject anything that fails — assume any
unsigned POST is a forgery.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import stripe
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.core.enums import BillingInterval, SubscriptionStatus, TenantStatus
from app.core.redis import redis_client
from app.modules.audit import repository as audit
from app.modules.billing import contracts, repository as billing_repo
from app.modules.stripe import schemas
from app.modules.tenants import repository as tenant_repo
from app.modules.tenants.models import Tenant

logger = logging.getLogger(__name__)
settings = get_settings()

# ── SDK setup ────────────────────────────────────────────────────────────────
# Configure the SDK once on module import. The keys are read from Settings
# (which reads .env) so swapping test ↔ live is a single env change.
stripe.api_key = settings.STRIPE_SECRET_KEY
stripe.api_version = settings.STRIPE_API_VERSION


# =============================================================================
# CHECKOUT SESSION  — POST /billing/stripe/checkout
# =============================================================================

async def create_checkout_session(
    db: AsyncSession,
    *,
    tenant: Tenant,
    payload: schemas.CheckoutCreateRequest,
) -> schemas.CheckoutCreateResponse:
    """
    Build a Stripe Checkout Session for the given plan + interval.

    Workflow:
      1. Resolve plan and pick the right Stripe price id (monthly | annual).
      2. Find or reuse the tenant's Stripe customer id.
      3. Create the session with metadata so the webhook can identify
         which tenant / plan the payment belongs to.
      4. Return the redirect URL — the frontend sends the browser there.
    """
    plan = await billing_repo.get_plan_by_public_id(db, public_id=payload.plan_public_id)
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found.")
    if not plan.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This plan is no longer available.",
        )

    # Pick the correct Stripe price for the chosen interval
    if payload.billing_interval == BillingInterval.ANNUAL:
        stripe_price_id = plan.stripe_annual_price_id
    else:
        stripe_price_id = plan.stripe_monthly_price_id

    if not stripe_price_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Plan '{plan.slug}' has no Stripe price id configured for "
                f"{payload.billing_interval.value} billing. "
                "Add it via PATCH /billing/admin/plans/{id}."
            ),
        )

    # Reuse customer id if this tenant has paid before
    existing_sub = await billing_repo.get_active_subscription(db, tenant_id=tenant.id)
    customer_id = existing_sub.stripe_customer_id if existing_sub else None

    success_url = payload.success_url or settings.STRIPE_CHECKOUT_SUCCESS_URL
    cancel_url  = payload.cancel_url  or settings.STRIPE_CHECKOUT_CANCEL_URL

    # subscription_data lets us push trial + metadata onto the underlying
    # Subscription object Stripe will create on completion
    subscription_data: dict = {
        "metadata": {
            "tenant_public_id": tenant.public_id,
            "plan_public_id":   plan.public_id,
            "billing_interval": payload.billing_interval.value,
        },
    }
    if settings.STRIPE_DEFAULT_TRIAL_DAYS > 0:
        subscription_data["trial_period_days"] = settings.STRIPE_DEFAULT_TRIAL_DAYS

    session_kwargs: dict = {
        "mode": "subscription",
        "line_items": [{"price": stripe_price_id, "quantity": 1}],
        "success_url": success_url,
        "cancel_url":  cancel_url,
        "client_reference_id": tenant.public_id,
        "metadata": {
            "tenant_public_id": tenant.public_id,
            "plan_public_id":   plan.public_id,
            "billing_interval": payload.billing_interval.value,
        },
        "subscription_data": subscription_data,
        "allow_promotion_codes": True,
    }
    if customer_id:
        session_kwargs["customer"] = customer_id
    if payload.promotion_code:
        # Promo codes go in `discounts` when the user supplies an explicit code
        session_kwargs["discounts"] = [{"promotion_code": payload.promotion_code}]
        # discounts and allow_promotion_codes are mutually exclusive
        session_kwargs.pop("allow_promotion_codes", None)

    try:
        session = stripe.checkout.Session.create(**session_kwargs)
    except stripe.error.StripeError as exc:
        logger.exception("[stripe] checkout.Session.create failed tenant=%s plan=%s", tenant.public_id, plan.slug)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Stripe rejected the checkout request: {exc.user_message or str(exc)}",
        )

    logger.info(
        "[stripe] checkout session created tenant=%s plan=%s interval=%s session=%s",
        tenant.public_id, plan.slug, payload.billing_interval.value, session.id,
    )
    return schemas.CheckoutCreateResponse(session_id=session.id, url=session.url)


# =============================================================================
# CUSTOMER PORTAL  — POST /billing/stripe/portal
# =============================================================================

async def create_portal_session(
    db: AsyncSession,
    *,
    tenant: Tenant,
    payload: schemas.PortalCreateRequest,
) -> schemas.PortalCreateResponse:
    """
    Generate a one-time Customer Portal URL. Stripe handles cards, invoices,
    plan switches and cancellations on its hosted page — saves us building
    that UI.
    """
    sub = await billing_repo.get_active_subscription(db, tenant_id=tenant.id)
    if not sub or not sub.stripe_customer_id:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="No Stripe customer record. Complete a checkout first.",
        )

    return_url = payload.return_url or settings.STRIPE_PORTAL_RETURN_URL

    try:
        portal = stripe.billing_portal.Session.create(
            customer=sub.stripe_customer_id,
            return_url=return_url,
        )
    except stripe.error.StripeError as exc:
        logger.exception("[stripe] billing_portal.Session.create failed tenant=%s", tenant.public_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Stripe rejected the portal request: {exc.user_message or str(exc)}",
        )

    logger.info("[stripe] portal session created tenant=%s", tenant.public_id)
    return schemas.PortalCreateResponse(url=portal.url)


# =============================================================================
# WEBHOOK HANDLER  — POST /webhooks/stripe
# =============================================================================

# Set of Stripe event types we react to. Anything else is acknowledged with
# 200 OK and ignored — Stripe will stop re-sending after a successful 2xx.
_HANDLED_EVENTS = {
    "checkout.session.completed",
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "invoice.paid",
    "invoice.payment_succeeded",   # alias of paid in modern Stripe
    "invoice.payment_failed",
}


def _verify_signature(payload_bytes: bytes, sig_header: Optional[str]) -> stripe.Event:
    """
    Verify the webhook signature and parse the event in one step.
    Raises HTTPException(400) on any failure — we never trust unsigned input.
    """
    if not sig_header:
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature header.")
    try:
        event = stripe.Webhook.construct_event(
            payload=payload_bytes,
            sig_header=sig_header,
            secret=settings.STRIPE_WEBHOOK_SECRET,
        )
    except (ValueError, stripe.error.SignatureVerificationError) as exc:
        logger.warning("[stripe] webhook signature verification failed: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid signature.")
    return event


async def _is_duplicate_event(event_id: str) -> bool:
    """
    SET NX lock keyed by Stripe event id. Returns True when this event id
    has already been processed — caller short-circuits with a 200 OK so
    Stripe stops retrying.
    """
    key = f"stripe:event:{event_id}"
    # SET NX EX — acquire the slot only if it doesn't already exist
    acquired = await redis_client.set(
        key, "1",
        nx=True,
        ex=settings.STRIPE_WEBHOOK_IDEMPOTENCY_TTL_SECONDS,
    )
    return acquired is None  # acquired == None means key already existed


async def handle_webhook_event(
    db: AsyncSession,
    *,
    payload_bytes: bytes,
    sig_header: Optional[str],
) -> dict:
    """
    Top-level webhook handler.

    Returns a small dict the API layer echoes back as JSON — primarily for
    debugging in Stripe's webhook dashboard.
    """
    event = _verify_signature(payload_bytes, sig_header)
    event_id = event["id"]
    event_type = event["type"]
    logger.info("[stripe] webhook received id=%s type=%s", event_id, event_type)

    if event_type not in _HANDLED_EVENTS:
        logger.debug("[stripe] webhook ignored type=%s id=%s", event_type, event_id)
        return {"status": "ignored", "event_type": event_type}

    if await _is_duplicate_event(event_id):
        logger.info("[stripe] webhook duplicate id=%s type=%s", event_id, event_type)
        return {"status": "duplicate", "event_type": event_type}

    obj = event["data"]["object"]
    try:
        if event_type == "checkout.session.completed":
            await _on_checkout_completed(db, session=obj)
        elif event_type in ("customer.subscription.created", "customer.subscription.updated"):
            await _on_subscription_updated(db, sub_object=obj)
        elif event_type == "customer.subscription.deleted":
            await _on_subscription_deleted(db, sub_object=obj)
        elif event_type in ("invoice.paid", "invoice.payment_succeeded"):
            await _on_invoice_paid(db, invoice=obj)
        elif event_type == "invoice.payment_failed":
            await _on_invoice_failed(db, invoice=obj)
    except HTTPException:
        # Bubble up our deliberate errors (400/404 etc) so Stripe sees them
        raise
    except Exception:
        logger.exception("[stripe] webhook handler crashed event_id=%s type=%s", event_id, event_type)
        # 500 → Stripe retries. Re-raise so the API layer returns 500.
        raise

    return {"status": "processed", "event_type": event_type}


# ── Handlers per event type ──────────────────────────────────────────────────

async def _on_checkout_completed(db: AsyncSession, *, session: dict) -> None:
    """
    First-time activation: tenant just paid via Checkout.
    Stripe attaches our metadata to the session so we know who/what.
    """
    metadata = session.get("metadata") or {}
    tenant_public_id = metadata.get("tenant_public_id") or session.get("client_reference_id")
    plan_public_id   = metadata.get("plan_public_id")
    stripe_subscription_id = session.get("subscription")
    stripe_customer_id     = session.get("customer")

    if not tenant_public_id or not plan_public_id:
        logger.error("[stripe] checkout.completed missing metadata session_id=%s", session.get("id"))
        return

    tenant = await tenant_repo.get_tenant_by_public_id(db, public_id=tenant_public_id)
    plan   = await billing_repo.get_plan_by_public_id(db, public_id=plan_public_id)
    if not tenant or not plan:
        logger.error(
            "[stripe] checkout.completed unknown tenant=%s plan=%s",
            tenant_public_id, plan_public_id,
        )
        return

    # Activate via the existing contract — keeps subscription state in one place.
    sub = await contracts.activate_subscription(
        db,
        tenant=tenant,
        plan_id=plan.id,
        currency=(session.get("currency") or "AUD").upper(),
        trial_days=0,  # trial is handled by Stripe itself when configured
        notes=f"Activated via Stripe Checkout session {session.get('id')}.",
    )
    sub.stripe_subscription_id = stripe_subscription_id
    sub.stripe_customer_id     = stripe_customer_id

    await audit.write_system(
        db,
        entity_type="subscriptions",
        action=audit.ACTIVATE,
        tenant_id=tenant.id,
        entity_id=sub.id,
        diff={"after": {
            "plan_slug":              plan.slug,
            "stripe_subscription_id": stripe_subscription_id,
            "stripe_customer_id":     stripe_customer_id,
            "source":                 "stripe_checkout",
        }},
    )
    await db.commit()
    logger.info(
        "[stripe] subscription activated tenant=%s plan=%s stripe_sub=%s",
        tenant_public_id, plan.slug, stripe_subscription_id,
    )


async def _on_subscription_updated(db: AsyncSession, *, sub_object: dict) -> None:
    """
    Plan changed in Stripe (e.g. user switched monthly → annual via Portal),
    OR Stripe pushed a status change like trialing → active.
    """
    stripe_sub_id = sub_object.get("id")
    sub = await billing_repo.get_subscription_by_stripe_subscription_id(
        db, stripe_subscription_id=stripe_sub_id,
    )
    if not sub:
        logger.warning("[stripe] subscription.updated unknown stripe_sub=%s", stripe_sub_id)
        return

    # Map Stripe status → our SubscriptionStatus
    new_status = _map_stripe_status(sub_object.get("status"))
    old_status = sub.status

    # Detect plan change — first item's price id
    items = (sub_object.get("items") or {}).get("data") or []
    new_price_id = items[0]["price"]["id"] if items else None
    plan_changed = False
    if new_price_id:
        new_plan = await billing_repo.get_plan_by_stripe_price_id(
            db, stripe_price_id=new_price_id,
        )
        if new_plan and new_plan.id != sub.plan_id:
            sub.plan_id = new_plan.id
            plan_changed = True

    sub.status = new_status
    period_end = sub_object.get("current_period_end")
    period_start = sub_object.get("current_period_start")
    if period_end:
        sub.current_period_end = datetime.fromtimestamp(period_end, tz=timezone.utc)
    if period_start:
        sub.current_period_start = datetime.fromtimestamp(period_start, tz=timezone.utc)
    sub.cancel_at_period_end = bool(sub_object.get("cancel_at_period_end"))

    # Keep tenant.status in sync with subscription health
    tenant = await tenant_repo.get_tenant_by_id(db, tenant_id=sub.tenant_id)
    if tenant:
        if new_status == SubscriptionStatus.ACTIVE:
            tenant.status = TenantStatus.ACTIVE
        elif new_status == SubscriptionStatus.TRIALING:
            tenant.status = TenantStatus.TRIAL

    await audit.write_system(
        db,
        entity_type="subscriptions",
        action=audit.UPDATE,
        tenant_id=sub.tenant_id,
        entity_id=sub.id,
        diff={
            "before": {"status": old_status.value},
            "after":  {"status": new_status.value, "plan_changed": plan_changed},
        },
    )
    await db.commit()
    logger.info(
        "[stripe] subscription updated stripe_sub=%s status=%s→%s plan_changed=%s",
        stripe_sub_id, old_status.value, new_status.value, plan_changed,
    )


async def _on_subscription_deleted(db: AsyncSession, *, sub_object: dict) -> None:
    """Final cancellation event from Stripe — mark cancelled in our DB."""
    stripe_sub_id = sub_object.get("id")
    sub = await billing_repo.get_subscription_by_stripe_subscription_id(
        db, stripe_subscription_id=stripe_sub_id,
    )
    if not sub:
        logger.warning("[stripe] subscription.deleted unknown stripe_sub=%s", stripe_sub_id)
        return

    sub.status = SubscriptionStatus.CANCELLED
    sub.cancelled_at = datetime.now(timezone.utc)

    tenant = await tenant_repo.get_tenant_by_id(db, tenant_id=sub.tenant_id)
    if tenant:
        tenant.status = TenantStatus.CANCELLED

    await audit.write_system(
        db,
        entity_type="subscriptions",
        action=audit.CANCEL,
        tenant_id=sub.tenant_id,
        entity_id=sub.id,
        diff={"after": {"status": "cancelled", "source": "stripe_webhook"}},
    )
    await db.commit()
    logger.info("[stripe] subscription cancelled stripe_sub=%s", stripe_sub_id)


async def _on_invoice_paid(db: AsyncSession, *, invoice: dict) -> None:
    """
    Successful renewal payment — lift PAST_DUE if we're in it, otherwise
    ensure ACTIVE. No-op when already active.
    """
    stripe_sub_id = invoice.get("subscription")
    if not stripe_sub_id:
        return  # one-off invoices we don't track

    sub = await billing_repo.get_subscription_by_stripe_subscription_id(
        db, stripe_subscription_id=stripe_sub_id,
    )
    if not sub:
        logger.warning("[stripe] invoice.paid unknown stripe_sub=%s", stripe_sub_id)
        return

    if sub.status == SubscriptionStatus.PAST_DUE:
        old = sub.status
        sub.status = SubscriptionStatus.ACTIVE
        tenant = await tenant_repo.get_tenant_by_id(db, tenant_id=sub.tenant_id)
        if tenant:
            tenant.status = TenantStatus.ACTIVE
        await audit.write_system(
            db,
            entity_type="subscriptions",
            action=audit.UPDATE,
            tenant_id=sub.tenant_id,
            entity_id=sub.id,
            diff={
                "before": {"status": old.value},
                "after":  {"status": "active", "source": "stripe_invoice_paid"},
            },
        )
        await db.commit()
        logger.info("[stripe] subscription restored to active stripe_sub=%s", stripe_sub_id)


async def _on_invoice_failed(db: AsyncSession, *, invoice: dict) -> None:
    """Payment failed — flip subscription to PAST_DUE so Gate 2 kicks in."""
    stripe_sub_id = invoice.get("subscription")
    if not stripe_sub_id:
        return

    sub = await billing_repo.get_subscription_by_stripe_subscription_id(
        db, stripe_subscription_id=stripe_sub_id,
    )
    if not sub:
        logger.warning("[stripe] invoice.payment_failed unknown stripe_sub=%s", stripe_sub_id)
        return

    if sub.status == SubscriptionStatus.PAST_DUE:
        return  # already there

    old = sub.status
    sub.status = SubscriptionStatus.PAST_DUE
    await audit.write_system(
        db,
        entity_type="subscriptions",
        action=audit.UPDATE,
        tenant_id=sub.tenant_id,
        entity_id=sub.id,
        diff={
            "before": {"status": old.value},
            "after":  {"status": "past_due", "source": "stripe_invoice_failed"},
        },
    )
    await db.commit()
    logger.warning("[stripe] subscription marked past_due stripe_sub=%s", stripe_sub_id)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _map_stripe_status(stripe_status: Optional[str]) -> SubscriptionStatus:
    """Translate Stripe's subscription.status enum to ours."""
    mapping = {
        "active":             SubscriptionStatus.ACTIVE,
        "trialing":           SubscriptionStatus.TRIALING,
        "past_due":           SubscriptionStatus.PAST_DUE,
        "unpaid":             SubscriptionStatus.PAST_DUE,
        "incomplete":         SubscriptionStatus.PAST_DUE,
        "incomplete_expired": SubscriptionStatus.CANCELLED,
        "canceled":           SubscriptionStatus.CANCELLED,
        "paused":             SubscriptionStatus.PAUSED,
    }
    return mapping.get(stripe_status or "", SubscriptionStatus.ACTIVE)
