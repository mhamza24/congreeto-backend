# app/modules/billing/schemas.py
from __future__ import annotations

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.enums import (
    BillingInterval, SubscriptionStatus,
    AddonType, UsageMetric, LimitStatus,
)


# =============================================================================
# PLAN SCHEMAS
# =============================================================================

class PlanLimits(BaseModel):
    max_users:                   int = 3
    max_chatbots:                int = 1
    max_conversations_per_month: int = 750
    max_tokens_per_month:        int = 1_000_000
    max_tokens_per_conversation: int = 4_000
    max_documents:               int = 120
    max_pages_crawled:           int = 50
    max_listings:                int = 500
    max_storage_mb:              int = 1_000

    model_config = ConfigDict(extra="allow")  # allow future limit keys


class PlanCreateRequest(BaseModel):
    name:             str             = Field(..., min_length=1, max_length=100)
    slug:             str             = Field(..., min_length=1, max_length=100)
    description:      Optional[str]   = None
    billing_interval: BillingInterval = BillingInterval.MONTHLY
    price_aud_cents:  int             = Field(0, ge=0)
    price_usd_cents:  int             = Field(0, ge=0)
    limits:           PlanLimits      = Field(default_factory=PlanLimits)
    is_public:        bool            = True
    sort_order:       int             = 0

    model_config = ConfigDict(str_strip_whitespace=True)


class PlanUpdateRequest(BaseModel):
    name:            Optional[str]        = None
    description:     Optional[str]        = None
    price_aud_cents: Optional[int]        = Field(None, ge=0)
    price_usd_cents: Optional[int]        = Field(None, ge=0)
    limits:          Optional[PlanLimits] = None
    is_active:       Optional[bool]       = None
    is_public:       Optional[bool]       = None
    sort_order:      Optional[int]        = None

    model_config = ConfigDict(str_strip_whitespace=True)


class PlanResponse(BaseModel):
    public_id:        str
    name:             str
    slug:             str
    description:      Optional[str]
    billing_interval: BillingInterval
    price_aud_cents:  int
    price_usd_cents:  int
    price_aud:        float
    price_usd:        float
    limits:           dict
    is_active:        bool
    is_public:        bool
    sort_order:       int
    created_at:       datetime

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_plan(cls, plan) -> "PlanResponse":
        return cls(
            public_id        = plan.public_id,
            name             = plan.name,
            slug             = plan.slug,
            description      = plan.description,
            billing_interval = plan.billing_interval,
            price_aud_cents  = plan.price_aud_cents,
            price_usd_cents  = plan.price_usd_cents,
            price_aud        = plan.price_aud,
            price_usd        = plan.price_usd,
            limits           = plan.limits,
            is_active        = plan.is_active,
            is_public        = plan.is_public,
            sort_order       = plan.sort_order,
            created_at       = plan.created_at,
        )


# =============================================================================
# ADDON SCHEMAS
# =============================================================================

class AddonCreateRequest(BaseModel):
    name:            str       = Field(..., min_length=1, max_length=100)
    slug:            str       = Field(..., min_length=1, max_length=100)
    description:     Optional[str] = None
    type:            AddonType
    price_aud_cents: int       = Field(0, ge=0)
    price_usd_cents: int       = Field(0, ge=0)
    config:          dict      = Field(default_factory=dict)

    model_config = ConfigDict(str_strip_whitespace=True)


class AddonResponse(BaseModel):
    public_id:       str
    name:            str
    slug:            str
    description:     Optional[str]
    type:            AddonType
    price_aud_cents: int
    price_usd_cents: int
    price_aud:       float
    price_usd:       float
    config:          dict
    is_active:       bool

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_addon(cls, addon) -> "AddonResponse":
        return cls(
            public_id       = addon.public_id,
            name            = addon.name,
            slug            = addon.slug,
            description     = addon.description,
            type            = addon.type,
            price_aud_cents = addon.price_aud_cents,
            price_usd_cents = addon.price_usd_cents,
            price_aud       = addon.price_aud,
            price_usd       = addon.price_usd,
            config          = addon.config,
            is_active       = addon.is_active,
        )


# =============================================================================
# SUBSCRIPTION SCHEMAS
# =============================================================================

class ActivateSubscriptionRequest(BaseModel):
    """Admin manually activates after receiving payment."""
    plan_public_id: str
    currency:       str           = Field("AUD", pattern="^(AUD|USD)$")
    trial_days:     int           = Field(0, ge=0, le=365)
    notes:          Optional[str] = Field(
        None, max_length=1000,
        description="Payment details e.g. 'Paid AUD 300 via bank transfer. Ref: INV-001'"
    )


class ChangePlanRequest(BaseModel):
    plan_public_id: str
    currency:       str           = Field("AUD", pattern="^(AUD|USD)$")
    notes:          Optional[str] = Field(None, max_length=1000)


class CancelSubscriptionRequest(BaseModel):
    immediately: bool           = True
    notes:       Optional[str]  = Field(None, max_length=1000)


class StatusNoteRequest(BaseModel):
    """Generic request body for status-only transitions that carry an optional note."""
    notes: Optional[str] = Field(None, max_length=1000)


class SubscriptionResponse(BaseModel):
    public_id:            str
    status:               SubscriptionStatus
    currency:             str
    plan:                 PlanResponse
    current_period_start: Optional[datetime]
    current_period_end:   Optional[datetime]
    trial_ends_at:        Optional[datetime]
    cancelled_at:         Optional[datetime]
    cancel_at_period_end: bool
    notes:                Optional[str]
    created_at:           datetime

    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# ADDON SUBSCRIPTION SCHEMAS
# =============================================================================

class AddAddonRequest(BaseModel):
    addon_public_id: str
    quantity:        int           = Field(1, ge=1, le=100)
    currency:        str           = Field("AUD", pattern="^(AUD|USD)$")
    notes:           Optional[str] = Field(None, max_length=1000)


class RemoveAddonRequest(BaseModel):
    addon_public_id: str
    notes:           Optional[str] = Field(None, max_length=1000)


class TenantAddonResponse(BaseModel):
    public_id: str
    addon:     AddonResponse
    quantity:  int
    status:    SubscriptionStatus
    currency:  str
    notes:     Optional[str]

    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# USAGE SCHEMAS
# =============================================================================

class UsageMetricDetail(BaseModel):
    metric:     UsageMetric
    used:       int
    limit:      int
    percentage: float
    status:     LimitStatus
    warned_80:  bool
    warned_90:  bool


class TenantUsageSummary(BaseModel):
    period_month: str
    metrics:      List[UsageMetricDetail]


# =============================================================================
# BILLING OVERVIEW
# =============================================================================

class TenantBillingOverview(BaseModel):
    """Full billing context — used in tenant dashboard."""
    subscription:    Optional[SubscriptionResponse]
    addons:          List[TenantAddonResponse]
    usage:           TenantUsageSummary
    seats_used:      int
    seats_total:     int
    seats_remaining: int


# =============================================================================
# LIMIT CHECK (used by other modules before creating resources)
# =============================================================================

class LimitCheckResponse(BaseModel):
    """
    Returned by GET /billing/tenants/{id}/limits/{metric}
    Other modules call this before creating conversations, documents, etc.
    """
    metric:     UsageMetric
    used:       int
    limit:      int
    percentage: float
    status:     LimitStatus
    allowed:    bool   # False = hard block, True = proceed