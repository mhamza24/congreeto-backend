# models/enums.py
"""
SQLAlchemy-native enums mapped to PostgreSQL native ENUM types.

Rules:
- Name the Python enum to match the Postgres TYPE name exactly
  (SQLAlchemy uses the class name as the pg type name by default).
- Set create_type=False for enums that already exist in the DB
  (created by prior Alembic migrations). Flip to True on a fresh DB.
- values_callable=lambda x: [e.value for e in x] ensures Postgres sees
  the string values, not the Python member names.
"""

import enum
from sqlalchemy import Enum as PgEnum


# ─────────────────────────────────────────────────────────────────────────────
# Python Enum Definitions
# ─────────────────────────────────────────────────────────────────────────────

class TenantStatus(str, enum.Enum):
    """
    Gate 1 — checked by every API middleware before processing a request.

    pending_plan → redirect to paywall (tenant registered but no plan chosen)
    trial        → within free-trial window
    active       → paying customer, trial ended
    suspended    → manually blocked OR Stripe payment failure cascade
    cancelled    → churned; same 403 as suspended
    """
    PENDING_PLAN = "pending_plan"
    TRIAL        = "trial"
    ACTIVE       = "active"
    SUSPENDED    = "suspended"
    CANCELLED    = "cancelled"

class TenantUserStatus(str, enum.Enum):
    """
    Tenant-scoped user status — independent of global users.status.

    invited     → invite sent, user has not yet accepted
    active      → accepted and can access this tenant
    suspended   → blocked from this tenant only (global account unaffected)
    deactivated → manually removed but row kept for audit trail
    """
    INVITED     = "invited"
    ACTIVE      = "active"
    SUSPENDED   = "suspended"
    DEACTIVATED = "deactivated"


class UserStatus(str, enum.Enum):
    """
    invited   → created (via invitation or self-signup), email not yet verified
    active    → email verified; can log in normally
    inactive  → manually deactivated by tenant admin
    suspended → locked out (too many failed logins, abuse, etc.)
    """
    INVITED   = "invited"
    ACTIVE    = "active"
    INACTIVE  = "inactive"
    SUSPENDED = "suspended"


class TenantRole(str, enum.Enum):
    """
    owner   → exactly 1 per tenant (the person who registered the company)
    admin   → full access; invited by owner or another admin
    agent   → can view/respond to conversations; limited writes
    viewer  → read-only dashboard access
    """
    OWNER  = "owner"
    ADMIN  = "admin"
    AGENT  = "agent"
    VIEWER = "viewer"


class InquiryStatus(str, enum.Enum):
    """Status lifecycle for all three inquiry form types."""
    SUBMITTED = "submitted"
    REVIEWED  = "reviewed"
    CONTACTED = "contacted"
    QUALIFIED = "qualified"
    CONVERTED = "converted"
    ARCHIVED  = "archived"


class ChatbotIdentity(str, enum.Enum):
    """Matches existing chatbot_identity Postgres type from prior migration."""
    WEBSITE     = "website"
    VELOCE_DEMO = "veloce_demo"


class OTPPurpose(str, enum.Enum):
    """
    Drives which template is sent and which expiry applies.

    email_verification → 15-minute expiry, sent on signup / resend request
    password_reset     → 15-minute expiry, sent on "forgot password"
    login_otp          → 5-minute expiry, for passwordless / 2-FA flows (future)
    """
    EMAIL_VERIFICATION = "email_verification"
    PASSWORD_RESET     = "password_reset"
    LOGIN_OTP          = "login_otp"


class InvitationStatus(str, enum.Enum):
    """
    pending  → email sent, link not yet clicked
    accepted → user clicked link and completed registration
    expired  → token TTL elapsed (72 h) without acceptance
    revoked  → manually cancelled by the inviting admin
    """
    PENDING  = "pending"
    ACCEPTED = "accepted"
    EXPIRED  = "expired"
    REVOKED  = "revoked"


class ChatbotStatus(str, enum.Enum):
    DRAFT     = "draft"
    ACTIVE    = "active"
    INACTIVE  = "inactive"

class SourceType(str, enum.Enum):
    WEBSITE  = "website"
    PDF      = "pdf"
    TEXT     = "text"

class CrawlStatus(str, enum.Enum):
    QUEUED    = "queued"
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"
    CANCELLED = "cancelled"

class DocStatus(str, enum.Enum):
    UPLOADING  = "uploading"
    PROCESSING = "processing"
    READY      = "ready"
    FAILED     = "failed"

class ListingSource(str, enum.Enum):
    MANUAL  = "manual"
    CRAWLED = "crawled"

class ListingStatus(str, enum.Enum):
    ACTIVE   = "active"
    INACTIVE = "inactive"
    SOLD     = "sold"
    LEASED   = "leased"

class ListingType(str, enum.Enum):
    SALE  = "sale"
    RENT  = "rent"
# ─────────────────────────────────────────────────────────────────────────────
# SQLAlchemy / Postgres TYPE objects
# Use these in mapped_column(type_=...) declarations.
# ─────────────────────────────────────────────────────────────────────────────

# Set create_type=True on a fresh database; False if Alembic already created it.
tenant_status_enum = PgEnum(
    TenantStatus,
    name="tenant_status",
    create_type=True,
    values_callable=lambda x: [e.value for e in x],
)

tenant_user_status_enum = PgEnum(
    TenantUserStatus,
    name="tenant_user_status",
    create_type=True,
    values_callable=lambda x: [e.value for e in x],
)

user_status_enum = PgEnum(
    UserStatus,
    name="user_status",
    create_type=True,
    values_callable=lambda x: [e.value for e in x],
)

tenant_role_enum = PgEnum(
    TenantRole,
    name="tenant_role",
    create_type=True,
    values_callable=lambda x: [e.value for e in x],
)

inquiry_status_enum = PgEnum(
    InquiryStatus,
    name="inquirystatus",   # matches existing Postgres type name
    create_type=False,       # already created by prior migration
    values_callable=lambda x: [e.value for e in x],
)

chatbot_identity_enum = PgEnum(
    ChatbotIdentity,
    name="chatbot_identity",  # matches existing Postgres type name
    create_type=False,         # already created by prior migration
    values_callable=lambda x: [e.value for e in x],
)

otp_purpose_enum = PgEnum(
    OTPPurpose,
    name="otp_purpose",
    create_type=True,
    values_callable=lambda x: [e.value for e in x],
)

invitation_status_enum = PgEnum(
    InvitationStatus,
    name="invitation_status",
    create_type=True,
    values_callable=lambda x: [e.value for e in x],
)

chatbot_status_enum = PgEnum(
    ChatbotStatus,
    name="chatbot_status",
    create_type=True,
    values_callable=lambda x: [e.value for e in x],
)

source_type_enum = PgEnum(
    SourceType,
    name="source_type",
    create_type=True,
    values_callable=lambda x: [e.value for e in x],
)

crawl_status_enum = PgEnum(
    CrawlStatus,
    name="crawl_status",
    create_type=True,
    values_callable=lambda x: [e.value for e in x],
)

doc_status_enum = PgEnum(
    DocStatus,
    name="doc_status",
    create_type=True,
    values_callable=lambda x: [e.value for e in x],
)

listing_source_enum = PgEnum(
    ListingSource,
    name="listing_source",
    create_type=True,
    values_callable=lambda x: [e.value for e in x],
)

listing_status_enum = PgEnum(
    ListingStatus,
    name="listing_status",
    create_type=True,
    values_callable=lambda x: [e.value for e in x],
)

listing_type_enum = PgEnum(
    ListingType,
    name="listing_type",
    create_type=True,
    values_callable=lambda x: [e.value for e in x],
)