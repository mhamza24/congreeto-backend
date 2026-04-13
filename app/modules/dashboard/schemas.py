from pydantic import BaseModel
from typing import Dict, Optional, List


# ── Tenant dashboard (existing) ────────────────────────────────────────────────

class DashboardSummaryRequest(BaseModel):
    pass


class DashboardSummaryResponse(BaseModel):
    summary: Dict


# ── Super-admin analytics ──────────────────────────────────────────────────────

class TenantStatusBreakdown(BaseModel):
    total: int
    active: int
    trial: int
    pending_plan: int
    suspended: int
    cancelled: int


class PlanDistribution(BaseModel):
    plan_name: str
    plan_slug: str
    billing_interval: str
    subscriber_count: int
    revenue_aud: float


class RevenueMetrics(BaseModel):
    mrr_aud: float
    arr_aud: float
    active_subscriptions: int
    trialing_subscriptions: int
    past_due_subscriptions: int
    plan_distribution: List[PlanDistribution]


class LeadBreakdown(BaseModel):
    hot: int
    nurture: int
    cold: int
    total: int


class ChatbotStats(BaseModel):
    active: int
    draft: int
    inactive: int


class DailyActivity(BaseModel):
    day: str          # ISO date e.g. "2026-04-13"
    conversations: int
    leads_captured: int


class AdminOverviewResponse(BaseModel):
    tenants: TenantStatusBreakdown
    total_users: int
    total_conversations: int
    conversations_this_month: int
    active_conversations: int
    leads: LeadBreakdown
    revenue: RevenueMetrics
    chatbots: ChatbotStats
    daily_activity: List[DailyActivity]


class TenantRow(BaseModel):
    public_id: str
    name: str
    slug: str
    status: str
    plan_name: Optional[str] = None
    subscription_status: Optional[str] = None
    total_conversations: int
    member_count: int
    created_at: str


class AdminTenantsResponse(BaseModel):
    tenants: List[TenantRow]
    total: int
    limit: int
    offset: int
