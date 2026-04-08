# models/tenant_user.py
"""
TenantUser — bridge between a User and a Tenant.

One row per (tenant_id, user_id) pair.
The same human (User) can belong to multiple tenants with different roles.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHY A BRIDGE TABLE (not a tenant_id column on users)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  - A real-estate agent may work across multiple agencies simultaneously.
  - Each tenant can grant a different role to the same person
    (admin at Agency A, viewer at Agency B).
  - Removing a user from a tenant is a single DELETE on this table —
    the User row (and their auth history) remains intact.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ROLES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  owner   — exactly 1 per tenant (is_primary_owner=True).
            Set when the company first registers. Never via invite.
  admin   — full access, can invite other users.
  agent   — can view conversations, limited write access.
  viewer  — read-only access.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
USER LIMIT ENFORCEMENT (Gate 3)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Before inserting a new TenantUser, check the v_tenant_user_counts view:

      SELECT effective_limit, current_user_count
      FROM   v_tenant_user_counts
      WHERE  tenant_id = X;

      if current_user_count >= effective_limit:
          raise HTTPException(402, "User seat limit reached")

  effective_limit = plans.limits['max_users']
                  + SUM(addon qty WHERE addon.type = 'extra_users')

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FLAT COLUMNS vs JSONB — Decision record
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  All columns here are individually queried or used in permission checks.
  No JSONB appropriate — every field is filtered, indexed, or ordered.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INDEXES — Decision record
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ix_tenant_users_tenant — list all users in a tenant (dashboard)
  ix_tenant_users_user   — list all tenants a user belongs to (login)
  ix_tenant_users_role   — filter by role within a tenant (permission checks)

  UNIQUE(tenant_id, user_id) — enforced at DB level, one role per person
  per tenant. To change a role: UPDATE role WHERE (tenant_id, user_id).
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db_base import Base, PublicIdMixin
from app.core.enums import TenantRole, TenantUserStatus, tenant_role_enum,tenant_user_status_enum

if TYPE_CHECKING:
    from app.modules.tenants.models import Tenant
    from app.modules.users.models import User


class TenantUser(Base, PublicIdMixin):
    """
    Scoped bridge: links a User to a Tenant with a specific role.

    Security notes:
    - is_primary_owner must be exactly 1 per tenant. Enforce at the service
      layer; there is no DB constraint beyond the UNIQUE(tenant_id, user_id).
    - invited_by is NULL for the owner who self-registered.
      Populated for all subsequent users who were invited.
    - Removing a user from a tenant: DELETE this row.
      The User row is preserved; their chat history and audit trail remain.

    Usage examples:

        # Invite a new user (after Gate 3 seat-limit check)
        tu = TenantUser(
            tenant_id  = tenant.id,
            user_id    = user.id,
            role       = TenantRole.AGENT,
            invited_by = inviter_user.id,
        )

        # Seat limit check before invite
        counts = db.execute(
            select(v_tenant_user_counts)
            .where(v_tenant_user_counts.c.tenant_id == tenant.id)
        ).one()
        if counts.current_user_count >= counts.effective_limit:
            raise HTTPException(402, "User seat limit reached")

        # Permission check
        is_admin = tu.role in (TenantRole.OWNER, TenantRole.ADMIN)
    """

    __tablename__ = "tenant_users"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )

    # ── Foreign keys ──────────────────────────────────────────────────────────
    tenant_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        comment="The tenant (company) this membership belongs to.",
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        comment="The user being granted access to this tenant.",
    )

    # ── Role & ownership ──────────────────────────────────────────────────────
    role: Mapped[TenantRole] = mapped_column(
        tenant_role_enum,
        nullable=False,
        default=TenantRole.ADMIN,
        server_default=text("'admin'"),
        comment=(
            "owner=1 per tenant (primary owner) | "
            "admin=full access | agent=limited write | viewer=read-only."
        ),
    )

    is_primary_owner: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("FALSE"),
        comment=(
            "Exactly 1 TRUE per tenant. Set when the first user registers "
            "their company. Never set via the invite flow."
        ),
    )

    # ── Invite audit trail ────────────────────────────────────────────────────
    invited_by: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
        comment=(
            "NULL for the owner who self-registered. "
            "Populated with the inviter's user.id for all invited members."
        ),
    )

    # ── Lifecycle ─────────────────────────────────────────────────────────────
    joined_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        comment=(
            "Set when the invited user accepts the invite and completes signup. "
            "NULL means the invite is still pending."
        ),
    )

    status: Mapped[TenantUserStatus] = mapped_column(
    tenant_user_status_enum,
    nullable=False,
    default=TenantUserStatus.INVITED,
    server_default=text("'invited'"),
    comment=(
        "invited=pending | active=joined | "
        "suspended=blocked this tenant only | deactivated=removed"
    ),
)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
        comment="When the invite was created (or the owner self-registered).",
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    tenant: Mapped["Tenant"] = relationship(
        "Tenant",
        back_populates="tenant_users",
        lazy="noload",
        foreign_keys=[tenant_id],
    )

    user: Mapped["User"] = relationship(
        "User",
        back_populates="tenant_users",
        lazy="noload",
        foreign_keys=[user_id],
    )

    inviter: Mapped["User | None"] = relationship(
        "User",
        lazy="noload",
        foreign_keys=[invited_by],
        # No back_populates — inviter doesn't need a list of who they invited
        # on the User model itself; query TenantUser directly if needed.
    )

    # ── Constraints & indexes ─────────────────────────────────────────────────
    __table_args__ = (
        # One role per user per tenant — enforced at DB level.
        # To change a role: UPDATE role WHERE (tenant_id=X, user_id=Y).
        UniqueConstraint("tenant_id", "user_id",
                         name="uq_tenant_users_tenant_user"),

        # List all members of a tenant (dashboard user management page).
        Index("ix_tenant_users_tenant", "tenant_id"),

        # List all tenants a user belongs to (used at login to build JWT claims).
        Index("ix_tenant_users_user", "user_id"),

        # Permission checks within a tenant: filter by role.
        Index("ix_tenant_users_role", "tenant_id", "role"),
        
        # add this index to __table_args__
        Index("ix_tenant_users_status", "tenant_id", "status"),
    )

    # ── Computed helpers ──────────────────────────────────────────────────────
    @property
    def is_owner_or_admin(self) -> bool:
        return self.role in (TenantRole.OWNER, TenantRole.ADMIN)

    @property
    def can_write(self) -> bool:
        """Agents and above can perform write operations."""
        return self.role in (TenantRole.OWNER, TenantRole.ADMIN, TenantRole.AGENT)

    @property
    def has_joined(self) -> bool:
        """False while the invite is still pending."""
        return self.joined_at is not None

    def __repr__(self) -> str:
        return (
            f"<TenantUser tenant={self.tenant_id} "
            f"user={self.user_id} role={self.role}>"
        )

    @property
    def is_active(self) -> bool:
        return self.status == TenantUserStatus.ACTIVE

    @property
    def is_accessible(self) -> bool:
        """Use in middleware for tenant-scoped access checks."""
        return self.status == TenantUserStatus.ACTIVE