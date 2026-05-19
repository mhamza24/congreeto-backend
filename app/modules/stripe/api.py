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
from app.dependencies.user import get_verified_user
from app.modules.stripe import schemas, service

logger = logging.getLogger(__name__)

# Checkout/portal endpoints (user-scoped + tenant-scoped)
billing_stripe_router = APIRouter(prefix="/billing/stripe", tags=["Billing — Stripe"])

# Webhook lives outside /billing so the URL is clean for Stripe dashboard
webhook_router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

DBDep  = Annotated[AsyncSession, Depends(get_db)]
CtxDep = Annotated[TenantContext, Depends(get_tenant_context)]


# =============================================================================
# USER-SCOPED CHECKOUT  (no tenant needed — called from the paywall)
# Static paths must be declared BEFORE the /{tenant_public_id} parameterized
# paths so FastAPI routes them correctly.
# =============================================================================

@billing_stripe_router.post(
    "/checkout",
    response_model=ApiResponse[schemas.CheckoutCreateResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Create a Stripe Checkout Session for the authenticated user (paywall flow)",
)
async def create_user_checkout(
    payload: schemas.CheckoutCreateRequest,
    db: DBDep,
    current_user=Depends(get_verified_user),
) -> ApiResponse[schemas.CheckoutCreateResponse]:
    """
    Called from the paywall page. No tenant ID required — the user hasn't
    created a tenant yet. After payment the webhook creates a UserSubscription
    and the user is redirected to the dashboard to create their first workspace.
    """
    try:
        result = await service.create_user_checkout_session(
            db, user=current_user, payload=payload,
        )
    except HTTPException:
        raise
    except Exception:
        sentry_sdk.capture_exception()
        logger.exception("create_user_checkout failed user=%s", current_user.public_id)
        raise HTTPException(status_code=500, detail="Could not create Stripe checkout session.")
    return ApiResponse(success=True, message="Checkout session created.", data=result)


# =============================================================================
# USER-SCOPED PORTAL  (no tenant needed — manage billing from user settings)
# =============================================================================

@billing_stripe_router.post(
    "/portal",
    response_model=ApiResponse[schemas.PortalCreateResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Create a Stripe Customer Portal session for the authenticated user",
)
async def create_user_portal(
    payload: schemas.PortalCreateRequest,
    db: DBDep,
    current_user=Depends(get_verified_user),
) -> ApiResponse[schemas.PortalCreateResponse]:
    """
    Lets the owner manage their card, view invoices, or cancel from the
    user-level settings page. No tenant context required.
    """
    try:
        result = await service.create_user_portal_session(
            db, user=current_user, payload=payload,
        )
    except HTTPException:
        raise
    except Exception:
        sentry_sdk.capture_exception()
        logger.exception("create_user_portal failed user=%s", current_user.public_id)
        raise HTTPException(status_code=500, detail="Could not create Stripe portal session.")
    return ApiResponse(success=True, message="Portal session created.", data=result)


# =============================================================================
# TENANT-SCOPED CHECKOUT  (admin / future multi-tenant billing use)
# =============================================================================

@billing_stripe_router.post(
    "/{tenant_public_id}/checkout",
    response_model=ApiResponse[schemas.CheckoutCreateResponse],
    status_code=status.HTTP_201_CREATED,
    summary="[Admin] Create a Stripe Checkout Session scoped to a tenant",
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
# TENANT-SCOPED PORTAL  (admin / future multi-tenant billing use)
# =============================================================================

@billing_stripe_router.post(
    "/{tenant_public_id}/portal",
    response_model=ApiResponse[schemas.PortalCreateResponse],
    status_code=status.HTTP_201_CREATED,
    summary="[Admin] Create a Stripe Customer Portal session scoped to a tenant",
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
