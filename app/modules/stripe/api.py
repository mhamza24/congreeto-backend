"""
Stripe HTTP endpoints.

  POST /billing/stripe/checkout       — create a Checkout Session (auth required)
  POST /billing/stripe/portal         — create a Customer Portal session (auth required)
  POST /webhooks/stripe               — Stripe → us. NO auth, signature verified.

Notes
─────
- The webhook endpoint reads the raw request body. Do NOT replace `await
  request.body()` with a Pydantic-parsed model — Stripe's signature is
  computed over the exact bytes it sent, byte-for-byte. Any reformatting
  breaks verification.
- The webhook router is mounted separately from /billing/stripe so it can
  live at /webhooks/stripe (cleaner for Stripe dashboard config) and so the
  `tenant_public_id` URL pattern doesn't pollute it.
"""
from __future__ import annotations

import logging
from typing import Annotated

import sentry_sdk
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import ApiResponse
from app.dependencies.tenant import TenantContext, get_tenant_context, require_write
from app.modules.stripe import schemas, service

logger = logging.getLogger(__name__)

# Tenant-scoped checkout/portal endpoints
billing_stripe_router = APIRouter(prefix="/billing/stripe", tags=["Billing — Stripe"])

# Webhook lives outside /billing so the URL is clean for Stripe dashboard
webhook_router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

DBDep  = Annotated[AsyncSession, Depends(get_db)]
CtxDep = Annotated[TenantContext, Depends(get_tenant_context)]


# =============================================================================
# CHECKOUT
# =============================================================================

@billing_stripe_router.post(
    "/{tenant_public_id}/checkout",
    response_model=ApiResponse[schemas.CheckoutCreateResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Create a Stripe Checkout Session — frontend redirects user to .url",
)
async def create_checkout(
    payload: schemas.CheckoutCreateRequest,
    db: DBDep,
    ctx: CtxDep,
) -> ApiResponse[schemas.CheckoutCreateResponse]:
    require_write(ctx)
    try:
        result = await service.create_checkout_session(
            db, tenant=ctx.tenant, payload=payload,
        )
    except HTTPException:
        raise
    except Exception:
        sentry_sdk.capture_exception()
        logger.exception("create_checkout failed tenant=%s", ctx.tenant.public_id)
        raise HTTPException(status_code=500, detail="Could not create Stripe checkout session.")
    return ApiResponse(success=True, message="Checkout session created.", data=result)


# =============================================================================
# CUSTOMER PORTAL  (cards, invoices, plan changes, cancellations)
# =============================================================================

@billing_stripe_router.post(
    "/{tenant_public_id}/portal",
    response_model=ApiResponse[schemas.PortalCreateResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Create a Stripe Customer Portal session for billing self-service",
)
async def create_portal(
    payload: schemas.PortalCreateRequest,
    db: DBDep,
    ctx: CtxDep,
) -> ApiResponse[schemas.PortalCreateResponse]:
    require_write(ctx)
    try:
        result = await service.create_portal_session(
            db, tenant=ctx.tenant, payload=payload,
        )
    except HTTPException:
        raise
    except Exception:
        sentry_sdk.capture_exception()
        logger.exception("create_portal failed tenant=%s", ctx.tenant.public_id)
        raise HTTPException(status_code=500, detail="Could not create Stripe portal session.")
    return ApiResponse(success=True, message="Portal session created.", data=result)


# =============================================================================
# WEBHOOK  (Stripe → us)
# =============================================================================

@webhook_router.post(
    "/stripe",
    summary="Stripe webhook receiver — signature-verified",
    include_in_schema=True,
)
async def stripe_webhook(
    request: Request,
    db: DBDep,
) -> dict:
    """
    Verifies the Stripe signature, dedupes by event id, and dispatches to
    the relevant billing contract. Always returns 2xx for handled and
    duplicate events so Stripe stops retrying.

    Failures bubble as 4xx/5xx — Stripe will retry 5xx automatically with
    exponential backoff for ~3 days.
    """
    sig_header = request.headers.get("stripe-signature")
    payload_bytes = await request.body()

    try:
        result = await service.handle_webhook_event(
            db, payload_bytes=payload_bytes, sig_header=sig_header,
        )
    except HTTPException:
        # Signature errors etc — let Stripe see the 4xx without Sentry noise
        raise
    except Exception:
        sentry_sdk.capture_exception()
        logger.exception("stripe webhook handler crashed")
        # 500 → Stripe retries with backoff
        raise HTTPException(status_code=500, detail="Webhook processing error.")
    return result
