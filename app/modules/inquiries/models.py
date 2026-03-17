"""
SQLAlchemy ORM models for website inquiries.

Supports two inquiry types:

1. GeneralInquiry
   Standard contact form submissions.

2. DemoInquiry
   Demo requests from property businesses.

Design Goals
------------
• Internal numeric PK for efficient joins
• Public uuid7 identifier for API exposure
• Lifecycle status tracking
• Flexible sector/state storage using JSON
• Indexing for fast filtering and dashboards
"""

import enum
from datetime import datetime, timezone
from uuid6 import uuid7

from sqlalchemy import (
    Column,
    String,
    Text,
    BigInteger,
    DateTime,
    Enum,
    Index,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import ENUM
from app.core.db_base import Base


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_public_id() -> str:
    """Generate time-sortable UUID7 public identifier."""
    return str(uuid7())


# ---------------------------------------------------------------------
# Inquiry Lifecycle
# ---------------------------------------------------------------------

class InquiryStatus(str, enum.Enum):
    submitted = "submitted"
    reviewed = "reviewed"
    contacted = "contacted"
    qualified = "qualified"
    converted = "converted"
    archived = "archived"


    inquirystatus_enum = ENUM(
        "submitted", "reviewed", "contacted", "qualified", "converted", "archived",
        name="inquirystatus",
        create_type=False,  # avoid trying to recreate type in migrations
    )
    # ---------------------------------------------------------------------
# General Inquiry Model
# ---------------------------------------------------------------------


class GeneralInquiry(Base):
    __tablename__ = "general_inquiries"

    # Identity
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    public_id = Column(
        String,
        unique=True,
        nullable=False,
        default=new_public_id,
        comment="External identifier (uuid7)"
    )

    # Contact Details
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    email = Column(String, nullable=False)
    company_name = Column(String, nullable=True)

    subject = Column(String, nullable=False)
    message = Column(Text, nullable=False)

    # Lifecycle
    status = Column(
        Enum(InquiryStatus),
        nullable=False,
        default=InquiryStatus.submitted
    )

    # Metadata
    visitor_ip_hash = Column(String, nullable=True)
    visitor_ua = Column(String, nullable=True)
    page_url = Column(String, nullable=True)

    # Timestamps
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow
    )

    # Indexing
    __table_args__ = (
        Index("ix_general_inquiries_public_id", "public_id"),
        Index("ix_general_inquiries_status", "status"),
        Index("ix_general_inquiries_created_at", "created_at"),
        Index("ix_general_inquiries_email", "email"),
    )

    def __repr__(self) -> str:
        return (
            f"<GeneralInquiry public_id={self.public_id!r} "
            f"email={self.email!r}>"
        )


# ---------------------------------------------------------------------
# Demo Inquiry Model
# ---------------------------------------------------------------------

class DemoInquiry(Base):
    __tablename__ = "demo_inquiries"

    # Identity
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    public_id = Column(
        String,
        unique=True,
        nullable=False,
        default=new_public_id,
        comment="External identifier (uuid7)"
    )

    # Contact
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    email = Column(String, nullable=False)

    company_name = Column(String, nullable=False)
    company_website = Column(String, nullable=True)

    # Business Context
    property_sectors = Column(
        JSONB,
        nullable=True,
        comment="List of selected property sectors"
    )

    states = Column(
        JSONB,
        nullable=True,
        comment="List of selected Australian states"
    )

    message = Column(Text, nullable=True)

    # Lifecycle
    status = Column(
        Enum(InquiryStatus),
        nullable=False,
        default=InquiryStatus.submitted
    )

    # Metadata
    visitor_ip_hash = Column(String, nullable=True)
    visitor_ua = Column(String, nullable=True)
    page_url = Column(String, nullable=True)

    # Timestamps
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow
    )

    # Indexes
    __table_args__ = (
        Index("ix_demo_inquiries_public_id", "public_id"),
        Index("ix_demo_inquiries_status", "status"),
        Index("ix_demo_inquiries_created_at", "created_at"),
        Index("ix_demo_inquiries_email", "email"),
    )

    def __repr__(self) -> str:
        return (
            f"<DemoInquiry public_id={self.public_id!r} "
            f"company={self.company_name!r}>"
        )
