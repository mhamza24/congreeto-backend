"""
onboarding_models.py — SQLAlchemy ORM models for client onboarding and portfolio management.

Two new tables, designed to sit alongside the existing Conversation / Message schema.

─── Table 1: client_onboardings ────────────────────────────────────────────────
  Stores all raw content crawled or uploaded during client onboarding.
  Each source type (website crawl, Excel, Word, PDF) has its own JSON column
  so parsing pipelines stay independent and the raw data survives untouched.
  After cleaning, the content is embedded into a vector DB — this table is the
  permanent source-of-truth for what was fed to the LLM.

─── Table 2: portfolio_assets ──────────────────────────────────────────────────
  One row per property listing or portfolio file uploaded by the client.
  Stores the raw parsed content as JSON, plus metadata needed for display,
  filtering, and re-embedding when the client updates their portfolio.

Identity strategy (matches Conversation / Message):
  - `id`        : internal BigInteger surrogate PK — never exposed via API.
  - `public_id` : uuid7 string — time-sortable, used in all API responses.
  - `tenant_id` : multi-tenancy scoping key on every row.
"""

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import declarative_base, relationship

# Reuse the same Base, helpers and new_public_id from your existing models.py.
# If this file is separate, import them:
#   from .models import Base, utcnow, new_public_id
#
# For standalone clarity, they are re-declared here:

Base = declarative_base()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_public_id() -> str:
    from uuid6 import uuid7
    return str(uuid7())


# ─── Enums ────────────────────────────────────────────────────────────────────


class OnboardingStatus(str, enum.Enum):
    pending     = "pending"      # Row created, no processing started yet
    processing  = "processing"   # Actively being cleaned / embedded
    embedded    = "embedded"     # Successfully pushed to vector DB
    failed      = "failed"       # Processing failed — see error_log
    stale       = "stale"        # Source has been updated; re-embedding needed


class AssetType(str, enum.Enum):
    """
    What kind of source produced this portfolio asset.
    Determines which parser and prompt template to use downstream.
    """
    website_crawl  = "website_crawl"   # Crawled from a live URL
    pdf_upload     = "pdf_upload"      # Uploaded PDF (brochure, floorplan, etc.)
    word_upload    = "word_upload"     # Uploaded .docx file
    excel_upload   = "excel_upload"    # Uploaded .xlsx / .csv file
    manual_json    = "manual_json"     # Directly submitted as structured JSON (API / admin)


class AssetStatus(str, enum.Enum):
    raw        = "raw"        # Uploaded / crawled, not yet processed
    cleaned    = "cleaned"    # Cleaned and normalised, ready for embedding
    embedded   = "embedded"   # Embedded into vector DB
    archived   = "archived"   # No longer active; kept for audit trail
    failed     = "failed"     # Processing failed — see error_log


# ─────────────────────────────────────────────────────────────────────────────
# TABLE 1 — client_onboardings
# ─────────────────────────────────────────────────────────────────────────────

class ClientOnboarding(Base):
    """
    One row per onboarding run for a tenant.

    A single onboarding may include content from multiple sources:
      - A website crawl (stored in website_content_json)
      - One or more uploaded files (Excel, Word, PDF — each has its own column)

    All raw content is stored as JSON / large text so:
      1. The original source survives intact for audit and re-processing.
      2. Downstream cleaning and embedding pipelines are fully decoupled.
      3. You can re-embed without re-crawling or re-uploading.

    Embedding flow:
      crawl / upload → store raw here → clean → embed to vector DB
                                           ↑
                                    update status + embedding_ids
    """

    __tablename__ = "client_onboardings"

    # ── Identity ───────────────────────────────────────────────────────────────
    id = Column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
        comment="Internal surrogate PK. Never exposed via API.",
    )
    public_id = Column(
        String,
        unique=True,
        nullable=False,
        default=new_public_id,
        comment="External identifier (uuid7). Exposed in API responses.",
    )
    tenant_id = Column(
        String,
        nullable=False,
        index=True,
        comment="Tenant scoping key. All queries should filter on this.",
    )

    # ── Client Metadata ────────────────────────────────────────────────────────
    client_name = Column(
        String,
        nullable=False,
        comment="Human-readable name for this client / project (e.g. 'Vilara Park').",
    )
    client_domain = Column(
        String,
        nullable=True,
        comment="Primary website domain for this client (e.g. 'vilarapark.com.au').",
    )
    chatbot_identity = Column(
        String,
        nullable=True,
        comment=(
            "Which ARIA identity this onboarding belongs to "
            "(e.g. 'veloce_demo'). Matches ChatbotIdentity enum in models.py."
        ),
    )

    # ── Source: Website Crawl ─────────────────────────────────────────────────
    website_url = Column(
        String,
        nullable=True,
        comment="Root URL that was crawled. Null if no website crawl was performed.",
    )
    website_content_json = Column(
        Text,
        nullable=True,
        comment=(
            "Raw crawled website content stored as a JSON string. "
            "Structure: {pages: [{url, title, body_text, crawled_at}]}. "
            "Kept raw — cleaning happens downstream before embedding."
        ),
    )
    website_crawled_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp of the most recent successful crawl.",
    )

    # ── Source: Excel / CSV Upload ─────────────────────────────────────────────
    excel_filename = Column(
        String,
        nullable=True,
        comment="Original filename of the uploaded Excel / CSV file.",
    )
    excel_content_json = Column(
        Text,
        nullable=True,
        comment=(
            "Parsed Excel / CSV content stored as a JSON string. "
            "Structure: {sheets: [{sheet_name, rows: [{col: value}]}]}. "
            "Preserves all sheets and raw cell values before any normalisation."
        ),
    )
    excel_uploaded_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ── Source: Word / DOCX Upload ─────────────────────────────────────────────
    word_filename = Column(
        String,
        nullable=True,
        comment="Original filename of the uploaded Word document.",
    )
    word_content_json = Column(
        Text,
        nullable=True,
        comment=(
            "Parsed Word document content stored as a JSON string. "
            "Structure: {sections: [{heading, paragraphs: [text], tables: [[row]]}]}. "
            "Preserves document hierarchy before any cleaning."
        ),
    )
    word_uploaded_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ── Source: PDF Upload ─────────────────────────────────────────────────────
    pdf_filename = Column(
        String,
        nullable=True,
        comment="Original filename of the uploaded PDF.",
    )
    pdf_content_json = Column(
        Text,
        nullable=True,
        comment=(
            "Parsed PDF content stored as a JSON string. "
            "Structure: {pages: [{page_number, text, tables: [[row]]}]}. "
            "Raw extraction only — OCR output if scanned."
        ),
    )
    pdf_uploaded_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ── Processing Pipeline ────────────────────────────────────────────────────
    status = Column(
        Enum(OnboardingStatus),
        nullable=False,
        default=OnboardingStatus.pending,
        comment="Tracks where this onboarding is in the clean → embed pipeline.",
    )
    cleaned_content_json = Column(
        Text,
        nullable=True,
        comment=(
            "Merged and cleaned content from all sources, stored as a JSON string. "
            "This is the final version sent to the embedding model. "
            "Structure: {chunks: [{chunk_id, source_type, source_ref, text}]}."
        ),
    )
    embedding_model = Column(
        String,
        nullable=True,
        comment="Embedding model used (e.g. 'text-embedding-3-large'). Set after embedding.",
    )
    embedding_ids_json = Column(
        Text,
        nullable=True,
        comment=(
            "JSON array of vector DB record IDs produced by the embedding run. "
            "Used to identify and delete/update stale vectors when re-embedding. "
            "Example: '[\"vec_abc123\", \"vec_def456\"]'."
        ),
    )
    total_chunks_embedded = Column(
        Integer,
        nullable=True,
        comment="Number of text chunks successfully embedded in this run.",
    )
    error_log = Column(
        Text,
        nullable=True,
        comment="Last error message or traceback if status is 'failed'.",
    )

    # ── Timestamps ─────────────────────────────────────────────────────────────
    embedded_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp of the last successful embedding run.",
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )

    # ── Relationships ──────────────────────────────────────────────────────────
    portfolio_assets = relationship(
        "PortfolioAsset",
        back_populates="onboarding",
        lazy="select",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    # ── Indexes ────────────────────────────────────────────────────────────────
    __table_args__ = (
        # Primary list view: all onboardings for a tenant
        Index("ix_onboardings_tenant_created", "tenant_id", "created_at"),
        # Pipeline dashboard: find all rows that need processing
        Index("ix_onboardings_status", "status"),
        # Public ID lookup
        Index("ix_onboardings_public_id", "public_id"),
        # Stale detection: find onboardings for a domain to check for updates
        Index("ix_onboardings_domain", "client_domain"),
    )

    def __repr__(self) -> str:
        return (
            f"<ClientOnboarding "
            f"public_id={self.public_id!r} "
            f"client={self.client_name!r} "
            f"tenant={self.tenant_id!r} "
            f"status={self.status!r}>"
        )


# ─────────────────────────────────────────────────────────────────────────────
# TABLE 2 — portfolio_assets
# ─────────────────────────────────────────────────────────────────────────────

class PortfolioAsset(Base):
    """
    One row per property listing or portfolio file uploaded by the client.

    A PortfolioAsset is the granular unit of the portfolio — one apartment,
    one house design, one terrace, one brochure PDF, etc.

    It links back to the ClientOnboarding that produced it so you always know
    which source file a listing came from and can re-process if that source changes.

    The raw_content_json column stores the parsed, unparsed source data exactly
    as extracted — the same pattern as ClientOnboarding. ARIA uses the
    structured_content_json (cleaned, normalised) for matching and conversation.

    Embedding flow:
      ClientOnboarding → extract individual assets → store here as raw
                       → clean → structured_content_json
                       → embed → vector DB (embedding_id links back here)
    """

    __tablename__ = "portfolio_assets"

    # ── Identity ───────────────────────────────────────────────────────────────
    id = Column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
        comment="Internal surrogate PK. Never exposed via API.",
    )
    public_id = Column(
        String,
        unique=True,
        nullable=False,
        default=new_public_id,
        comment="External identifier (uuid7). Used in API responses and ARIA matching.",
    )
    tenant_id = Column(
        String,
        nullable=False,
        index=True,
        comment="Tenant scoping key.",
    )

    # ── Parent Onboarding ──────────────────────────────────────────────────────
    onboarding_id = Column(
        BigInteger,
        ForeignKey("client_onboardings.id", ondelete="CASCADE"),
        nullable=True,
        comment=(
            "FK to the ClientOnboarding that produced this asset. "
            "Null if the asset was created directly (e.g. admin API upload)."
        ),
    )

    # ── Asset Identity ─────────────────────────────────────────────────────────
    asset_type = Column(
        Enum(AssetType),
        nullable=False,
        comment="Source type — determines which parser was used.",
    )
    listing_id = Column(
        String,
        nullable=True,
        comment=(
            "Client-assigned listing reference code "
            "(e.g. 'VIL-APT-102', 'VIL-HL-SOLARA'). "
            "Used by ARIA to reference listings in conversation. "
            "Unique per tenant."
        ),
    )
    title = Column(
        String,
        nullable=False,
        comment="Human-readable listing title (e.g. 'Residence 102 — Private Garden Apartment').",
    )
    collection_name = Column(
        String,
        nullable=True,
        comment=(
            "Which collection this asset belongs to "
            "(e.g. 'Apartments', 'House & Land', 'Terraces'). "
            "Used for filtering in the portfolio management UI."
        ),
    )
    source_filename = Column(
        String,
        nullable=True,
        comment="Original filename if sourced from a file upload. Null for website crawls.",
    )
    source_url = Column(
        String,
        nullable=True,
        comment="Source URL if crawled from a website. Null for file uploads.",
    )

    # ── Raw Content ────────────────────────────────────────────────────────────
    raw_content_json = Column(
        Text,
        nullable=True,
        comment=(
            "Raw extracted content for this asset, stored as a JSON string. "
            "For file uploads: the parsed section from the parent file. "
            "For website crawls: the raw page body. "
            "Never modified after initial extraction — source of truth for re-processing. "
            "\n"
            "For Vilara Park demo, this would contain the full listing dict from "
            "vilara_portfolio_prompt.py serialised as JSON."
        ),
    )

    # ── Structured / Cleaned Content ──────────────────────────────────────────
    structured_content_json = Column(
        Text,
        nullable=True,
        comment=(
            "Cleaned and normalised content, stored as a JSON string. "
            "This is what ARIA reads at runtime for property matching. "
            "Structure mirrors the portfolio prompt format: "
            "{listing_id, title, type, bedrooms, bathrooms, price_from, "
            "price_display, highlights, ideal_for, key_pitch, ...}. "
            "Updated whenever the asset is re-processed."
        ),
    )

    # ── Key Matching Fields (denormalized for fast filtering) ─────────────────
    # These are extracted from structured_content_json for SQL-level filtering.
    # Avoids JSON parsing on every query when ARIA needs to filter by budget/type.
    property_type = Column(
        String,
        nullable=True,
        comment="e.g. 'Apartment', 'House', 'Townhouse', 'Terrace'. Extracted from content.",
    )
    bedrooms = Column(
        Integer,
        nullable=True,
        comment="Number of bedrooms. Extracted from content for fast range queries.",
    )
    bathrooms = Column(
        Integer,
        nullable=True,
        comment="Number of bathrooms.",
    )
    price_from = Column(
        BigInteger,
        nullable=True,
        comment=(
            "Starting price in cents (integer) for reliable range comparisons. "
            "Null for 'price on application' listings. "
            "Example: $915,000 → 91500000."
        ),
    )
    is_available = Column(
        Boolean,
        nullable=False,
        default=True,
        comment="False when the listing is sold or withdrawn. Used to exclude from ARIA results.",
    )

    # ── Processing Pipeline ────────────────────────────────────────────────────
    status = Column(
        Enum(AssetStatus),
        nullable=False,
        default=AssetStatus.raw,
        comment="Processing status — tracks raw → cleaned → embedded lifecycle.",
    )
    embedding_model = Column(
        String,
        nullable=True,
        comment="Embedding model used for this asset (e.g. 'text-embedding-3-large').",
    )
    embedding_id = Column(
        String,
        nullable=True,
        comment=(
            "Primary vector DB record ID for this asset. "
            "Used to update or delete the vector when content changes. "
            "If the asset was split into multiple chunks, use embedding_ids_json instead."
        ),
    )
    embedding_ids_json = Column(
        Text,
        nullable=True,
        comment=(
            "JSON array of all vector IDs if the asset was split into chunks. "
            "Supersedes embedding_id when multiple vectors exist for one asset."
        ),
    )
    error_log = Column(
        Text,
        nullable=True,
        comment="Last error message if status is 'failed'.",
    )

    # ── Timestamps ─────────────────────────────────────────────────────────────
    embedded_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp of the last successful embedding.",
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )

    # ── Relationships ──────────────────────────────────────────────────────────
    onboarding = relationship(
        "ClientOnboarding",
        back_populates="portfolio_assets",
    )

    # ── Indexes ────────────────────────────────────────────────────────────────
    __table_args__ = (
        # Primary list view: all assets for a tenant
        Index("ix_portfolio_assets_tenant_created", "tenant_id", "created_at"),

        # Listing ID lookup (used by ARIA to reference a specific listing)
        Index("ix_portfolio_assets_listing_id", "tenant_id", "listing_id"),

        # Collection filtering in portfolio UI
        Index("ix_portfolio_assets_collection", "tenant_id", "collection_name"),

        # Property type + availability filter (ARIA matching queries)
        Index("ix_portfolio_assets_type_available", "tenant_id", "property_type", "is_available"),

        # Budget range filtering (ARIA matching queries)
        # Example: WHERE tenant_id = ? AND price_from BETWEEN ? AND ? AND is_available = true
        Index("ix_portfolio_assets_price", "tenant_id", "price_from", "is_available"),

        # Bedroom count filter (common ARIA qualifier)
        Index("ix_portfolio_assets_bedrooms", "tenant_id", "bedrooms", "is_available"),

        # Pipeline dashboard: find assets needing embedding
        Index("ix_portfolio_assets_status", "tenant_id", "status"),

        # Parent onboarding lookup
        Index("ix_portfolio_assets_onboarding", "onboarding_id"),

        # Public ID lookup
        Index("ix_portfolio_assets_public_id", "public_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<PortfolioAsset "
            f"public_id={self.public_id!r} "
            f"listing_id={self.listing_id!r} "
            f"title={self.title!r} "
            f"status={self.status!r}>"
        )


# ─────────────────────────────────────────────────────────────────────────────
# USAGE NOTES
# ─────────────────────────────────────────────────────────────────────────────
#
# ONBOARDING FLOW:
#
#   1. Client submits website URL and/or uploads files.
#   2. Create a ClientOnboarding row with status=pending.
#   3. Crawl/parse each source → write raw JSON into the appropriate column.
#   4. Set status=processing, merge all sources → write to cleaned_content_json.
#   5. Chunk cleaned_content_json → embed → write embedding IDs back.
#   6. Set status=embedded, record embedded_at.
#
# PORTFOLIO ASSET FLOW:
#
#   1. After onboarding, extract individual listings from cleaned_content_json.
#   2. Create one PortfolioAsset row per listing with status=raw.
#   3. Populate raw_content_json with the listing's raw source dict.
#   4. Clean and normalise → write to structured_content_json.
#   5. Populate denormalised fields (property_type, bedrooms, price_from, etc.)
#      so ARIA can filter with SQL without parsing JSON on every query.
#   6. Embed the structured content → write embedding_id(s).
#   7. Set status=embedded.
#
# RE-EMBEDDING ON UPDATE:
#
#   - Set status=stale on the affected ClientOnboarding.
#   - Re-crawl / re-upload → overwrite the relevant JSON column.
#   - Re-clean → overwrite cleaned_content_json.
#   - Delete old vectors using embedding_ids_json.
#   - Re-embed → overwrite embedding_ids_json, update embedded_at.
#   - Set status=embedded.
#
# VILARA PARK DEMO — HOW TO SEED:
#
#   from vilara_portfolio_prompt import veloce_portfolio
#   import json
#
#   onboarding = ClientOnboarding(
#       tenant_id="veloce_demo",
#       client_name="Vilara Park",
#       client_domain="vilarapark.com.au",
#       chatbot_identity="veloce_demo",
#       excel_filename="vilara_portfolio_prompt.py",
#       excel_content_json=json.dumps(veloce_portfolio),
#       status=OnboardingStatus.pending,
#   )
#   session.add(onboarding)
#   session.flush()
#
#   # Then for each listing in veloce_portfolio["ApartmentCollection"]["Listings"]:
#   for listing in veloce_portfolio["ApartmentCollection"]["Listings"]:
#       asset = PortfolioAsset(
#           tenant_id="veloce_demo",
#           onboarding_id=onboarding.id,
#           asset_type=AssetType.manual_json,
#           listing_id=listing["ListingID"],
#           title=listing["Title"],
#           collection_name="Apartments",
#           raw_content_json=json.dumps(listing),
#           property_type=listing["Type"],
#           bedrooms=listing["Bedrooms"],
#           bathrooms=listing["Bathrooms"],
#           price_from=listing["PriceFrom"] * 100 if listing["PriceFrom"] else None,
#           is_available=listing["Availability"] == "Available",
#           status=AssetStatus.raw,
#       )
#       session.add(asset)
#   session.commit()