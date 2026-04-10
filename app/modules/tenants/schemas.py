from __future__ import annotations

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field, field_validator
import re

from app.core.enums import TenantStatus, TenantRole, TenantUserStatus


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
    settings: dict = Field(default_factory=dict)


class TenantUpdateRequest(BaseModel):
    name:     Optional[str]  = Field(None, min_length=1, max_length=255)
    industry: Optional[str]  = Field(None, max_length=100)
    settings: Optional[dict] = None

    model_config = ConfigDict(str_strip_whitespace=True)


class TenantStatusUpdateRequest(BaseModel):
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
    role: TenantRole

    @field_validator("role")
    @classmethod
    def cannot_assign_owner(cls, v: TenantRole) -> TenantRole:
        if v == TenantRole.OWNER:
            raise ValueError("Cannot assign 'owner' role via this endpoint.")
        return v


class UpdateMemberStatusRequest(BaseModel):
    """Admin/owner can suspend, reactivate, or deactivate a member within this tenant."""
    status: TenantUserStatus

    @field_validator("status")
    @classmethod
    def cannot_set_invited(cls, v: TenantUserStatus) -> TenantUserStatus:
        if v == TenantUserStatus.INVITED:
            raise ValueError("Cannot manually set status to 'invited'.")
        return v


class AcceptInviteRequest(BaseModel):
    code:      str = Field(..., description="One-time OTP code from the invite email link.")
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
    public_id:        str
    role:             TenantRole
    status:           TenantUserStatus
    is_primary_owner: bool
    joined_at:        Optional[datetime]
    created_at:       datetime

    user_public_id:  str
    email:           str
    first_name:      Optional[str]
    last_name:       Optional[str]
    avatar_url:      Optional[str]
    user_last_login: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class InviteResponse(BaseModel):
    message:        str = "Invitation sent successfully."
    email:          str
    role:           TenantRole
    expires_at:     datetime
    seats_used:     int
    seats_total:    int
    seats_remaining: int


class AcceptInviteResponse(BaseModel):
    message:   str = "Invitation accepted. Welcome aboard."
    public_id: str


class MemberListResponse(BaseModel):
    total:           int
    seats_used:      int
    seats_total:     int
    seats_remaining: int
    me:              Optional[TenantMemberResponse]
    members:         List[TenantMemberResponse]


class RemoveMemberResponse(BaseModel):
    message: str = "Member removed from tenant successfully."


# =============================================================================
# CURRENT USER TENANT CONTEXT
# =============================================================================

class MyTenantContext(BaseModel):
    tenant:          TenantSummary
    role:            TenantRole
    status:          TenantUserStatus
    is_owner:        bool
    joined_at:       Optional[datetime]
    seats_used:      int
    seats_total:     int
    seats_remaining: int
    # Gate 2 signal: True when subscription is past_due.
    # Frontend should surface a billing banner and block write UI.
    is_read_only:    bool

    model_config = ConfigDict(from_attributes=True)


class UserTenantItem(BaseModel):
    tenant:           TenantSummary
    role:             TenantRole
    status:           TenantUserStatus
    is_primary_owner: bool
    joined_at:        Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class UserTenantsResponse(BaseModel):
    total:   int
    tenants: List[UserTenantItem]