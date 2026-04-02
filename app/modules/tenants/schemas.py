# app/modules/tenants/schemas.py

from __future__ import annotations

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field, field_validator
import re

from app.core.enums import TenantStatus, TenantRole


# =============================================================================
# SHARED PRIMITIVES
# =============================================================================

class TenantBase(BaseModel):
    name:     str = Field(..., min_length=1, max_length=255)
    slug:     str = Field(..., min_length=2, max_length=100)
    industry: str = Field(default="real_estate", max_length=100)

    @field_validator("slug")
    @classmethod
    def slug_must_be_url_safe(cls, v: str) -> str:
        if not re.match(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", v):
            raise ValueError(
                "Slug must be lowercase alphanumeric with hyphens only. "
                "Example: 'acme-realty'"
            )
        return v

    model_config = ConfigDict(str_strip_whitespace=True)


# =============================================================================
# TENANT REQUEST SCHEMAS
# =============================================================================

class TenantCreateRequest(TenantBase):
    """
    Used by the owner registration flow.
    status is always forced to 'pending_plan' by the service layer via
    Tenant.from_schema(payload, status=TenantStatus.PENDING_PLAN).
    Clients must never set status.
    """
    settings: dict = Field(default_factory=dict)


class TenantUpdateRequest(BaseModel):
    """
    Partial update — all fields optional.
    Service uses model_dump(exclude_unset=True) so only sent fields are applied.
    """
    name:     Optional[str]  = Field(None, min_length=1, max_length=255)
    industry: Optional[str]  = Field(None, max_length=100)
    settings: Optional[dict] = None

    model_config = ConfigDict(str_strip_whitespace=True)


class TenantStatusUpdateRequest(BaseModel):
    """Super-admin only — manually change tenant status."""
    status: TenantStatus
    reason: Optional[str] = Field(None, max_length=500)


# =============================================================================
# TENANT RESPONSE SCHEMAS
# =============================================================================

class TenantResponse(BaseModel):
    public_id:     str
    name:          str
    slug:          str
    industry:      str
    status:        TenantStatus
    settings:      dict
    trial_ends_at: Optional[datetime]
    created_at:    datetime
    updated_at:    datetime

    model_config = ConfigDict(from_attributes=True)


class TenantSummary(BaseModel):
    """Lightweight — used inside list responses and JWT claims."""
    public_id: str
    name:      str
    slug:      str
    status:    TenantStatus
    industry:  str

    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# TENANT USER REQUEST SCHEMAS
# =============================================================================

class InviteUserRequest(BaseModel):
    """
    Sent by an admin/owner to invite a new member.
    Role defaults to 'agent'. Cannot invite as 'owner'.
    """
    email: str = Field(..., description="Email of the person to invite.")
    role:  TenantRole = Field(
        default=TenantRole.AGENT,
        description="Role to assign. Cannot be 'owner' via invite flow.",
    )

    @field_validator("role")
    @classmethod
    def cannot_invite_as_owner(cls, v: TenantRole) -> TenantRole:
        if v == TenantRole.OWNER:
            raise ValueError(
                "Cannot invite a user as 'owner'. "
                "The owner role is set only during company registration."
            )
        return v

    model_config = ConfigDict(str_strip_whitespace=True)


class UpdateMemberRoleRequest(BaseModel):
    """Change an existing member's role within the tenant."""
    role: TenantRole

    @field_validator("role")
    @classmethod
    def cannot_assign_owner(cls, v: TenantRole) -> TenantRole:
        if v == TenantRole.OWNER:
            raise ValueError("Cannot assign 'owner' role via this endpoint.")
        return v


class AcceptInviteRequest(BaseModel):
    """
    Submitted by the invitee when they click the invite link.
    from_schema maps first_name, last_name onto the User model.
    password and token are handled via overrides in the service.
    """
    token:      str = Field(..., description="Signed invite token from the email link.")
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name:  str = Field(..., min_length=1, max_length=100)
    password:   str = Field(..., min_length=8, max_length=100)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter.")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit.")
        return v

    model_config = ConfigDict(str_strip_whitespace=True)


# =============================================================================
# TENANT USER RESPONSE SCHEMAS
# =============================================================================

class TenantMemberResponse(BaseModel):
    """
    A user's membership record within a tenant.
    User profile fields are flattened for frontend convenience.
    """
    public_id:        str
    role:             TenantRole
    is_primary_owner: bool
    joined_at:        Optional[datetime]
    created_at:       datetime

    # User fields embedded
    user_public_id: str
    email:          str
    first_name:     Optional[str]
    last_name:      Optional[str]
    avatar_url:     Optional[str]

    model_config = ConfigDict(from_attributes=True)


class InviteResponse(BaseModel):
    """Returned after a successful invite is dispatched."""
    message:    str = "Invitation sent successfully."
    email:      str
    role:       TenantRole
    expires_at: datetime


class AcceptInviteResponse(BaseModel):
    """Returned after the invitee successfully accepts."""
    message:   str = "Invitation accepted. Welcome aboard."
    public_id: str


class MemberListResponse(BaseModel):
    """Paginated member list."""
    total:   int
    members: List[TenantMemberResponse]


class RemoveMemberResponse(BaseModel):
    message: str = "Member removed from tenant successfully."


# =============================================================================
# CURRENT USER TENANT CONTEXT
# =============================================================================

class MyTenantContext(BaseModel):
    """
    Returned to the authenticated user — shows their role inside a tenant.
    Used to build the dashboard sidebar and permission gates.
    """
    tenant:    TenantSummary
    role:      TenantRole
    is_owner:  bool
    joined_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)