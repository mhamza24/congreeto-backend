"""
Pydantic schemas for the Stripe checkout / portal endpoints.
The webhook endpoint receives raw bytes and verifies them with the Stripe SDK,
so it has no Pydantic body model.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import BillingInterval


class CheckoutCreateRequest(BaseModel):
    """
    Body for POST /billing/stripe/checkout.

    `plan_public_id` identifies the Plan row; `billing_interval` selects
    between the plan's monthly and annual Stripe price ids.
    """
    plan_public_id:   str = Field(..., min_length=1, max_length=64)
    billing_interval: BillingInterval = BillingInterval.MONTHLY
    # Optional overrides — if omitted, Settings defaults are used.
    success_url: Optional[str] = Field(default=None, max_length=2048)
    cancel_url:  Optional[str] = Field(default=None, max_length=2048)
    # Promo code the user typed in your UI. We pass it through to Stripe;
    # Stripe validates and applies it.
    promotion_code: Optional[str] = Field(default=None, max_length=64)

    model_config = ConfigDict(str_strip_whitespace=True)


class CheckoutCreateResponse(BaseModel):
    """Returned to the frontend after creating a Checkout Session."""
    session_id: str
    url:        str = Field(description="Redirect the user's browser to this URL.")


class PortalCreateRequest(BaseModel):
    """
    Body for POST /billing/stripe/portal.

    The Customer Portal is Stripe's hosted page where the customer can
    manage cards, view invoices, change plans, and cancel — we don't need
    to build any of that UI ourselves.
    """
    return_url: Optional[str] = Field(default=None, max_length=2048)

    model_config = ConfigDict(str_strip_whitespace=True)


class PortalCreateResponse(BaseModel):
    url: str = Field(description="Redirect the user's browser to this URL.")
