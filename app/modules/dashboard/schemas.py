from pydantic import BaseModel, Field
from typing import Dict, Optional, List
from datetime import datetime


# ── Tenant dashboard summary ───────────────────────────────────────────────────

class DashboardSummaryRequest(BaseModel):
    pass


class DashboardSummaryResponse(BaseModel):
    summary: Dict


# ── Leads list ────────────────────────────────────────────────────────────────

class PaginationMeta(BaseModel):
    page: int
    page_size: int
    total: int
    total_pages: int


class LeadListItem(BaseModel):
    public_id: str
    is_lead: bool
    lead_name: Optional[str] = None
    lead_email: Optional[str] = None
    lead_phone: Optional[str] = None
    total_messages: int
    summary: Optional[str] = None
    status: str
    last_activity_at: Optional[datetime] = None
    created_at: datetime
    lead_tier: Optional[str] = None
    lead_score: Optional[int] = None
    intent: Optional[str] = None
    sentiment: Optional[str] = None
    engagement_score: Optional[int] = None
    ai_summary: Optional[str] = None
    budget_min: Optional[int] = None
    budget_max: Optional[int] = None
    budget_currency: Optional[str] = None
    suburbs_mentioned: Optional[List[str]] = None
    property_types: Optional[List[str]] = None
    timeline: Optional[str] = None

    class Config:
        from_attributes = True


class LeadsListResponse(BaseModel):
    leads: List[LeadListItem]
    pagination: PaginationMeta


# ── Lead detail ───────────────────────────────────────────────────────────────

class MessageItem(BaseModel):
    public_id: str
    role: str
    content: str
    tokens_used: Optional[int] = None
    model_used: Optional[str] = None
    response_ms: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationStats(BaseModel):
    user_messages: int
    assistant_messages: int
    avg_response_ms: Optional[float] = None
    min_response_ms: Optional[int] = None
    max_response_ms: Optional[int] = None
    total_tokens_messages: Optional[int] = None
    first_message_at: Optional[datetime] = None
    last_message_at: Optional[datetime] = None
    conversation_duration_sec: Optional[float] = None


class LeadDetailResponse(BaseModel):
    public_id: str
    is_lead: bool
    lead_name: Optional[str] = None
    lead_email: Optional[str] = None
    lead_phone: Optional[str] = None
    total_messages: int
    total_tokens_used: int
    summary: Optional[str] = None
    running_summary: Optional[str] = None
    status: str
    page_url: Optional[str] = None
    last_activity_at: Optional[datetime] = None
    created_at: datetime
    closed_at: Optional[datetime] = None
    lead_score: Optional[int] = None
    lead_tier: Optional[str] = None
    intent: Optional[str] = None
    budget_min: Optional[int] = None
    budget_max: Optional[int] = None
    budget_currency: Optional[str] = None
    suburbs_mentioned: Optional[List[str]] = None
    cities_mentioned: Optional[List[str]] = None
    property_types: Optional[List[str]] = None
    bedrooms_wanted: Optional[int] = None
    timeline: Optional[str] = None
    sentiment: Optional[str] = None
    engagement_score: Optional[int] = None
    topics_mentioned: Optional[List[str]] = None
    ai_summary: Optional[str] = None
    ai_insights: Optional[str] = None
    processed_at: Optional[datetime] = None
    stats: ConversationStats
    messages: List[MessageItem]

    class Config:
        from_attributes = True


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
