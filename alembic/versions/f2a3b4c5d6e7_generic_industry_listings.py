"""generic_industry_listings

Revision ID: f2a3b4c5d6e7
Revises: b8c9d0e1f2a3
Create Date: 2026-05-06

Transforms the system from real-estate-specific to fully generic multi-industry:

  1.  Create `industry_schemas` table (per-industry prompts and field definitions)
  2.  Add `industry` + `listing_filter_config` to `chatbot_configs`, drop `allow_rental`
  3.  Rewrite `listings` table — drop RE columns, add `industry` + `attributes` JSONB
  4.  Rewrite `listing_upload_jobs` — add `chatbot_config_id` + `industry`
  5.  Rewrite `conversation_insights` — drop RE columns, add `industry_insights` JSONB
  6.  Seed four starter IndustrySchema rows (real_estate, restaurant, ecommerce, clinic)
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# ---------------------------------------------------------------------------
revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
# ---------------------------------------------------------------------------


def upgrade() -> None:
    # ── 1. industry_schemas ──────────────────────────────────────────────────
    op.create_table(
        "industry_schemas",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("industry", sa.String(100), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("listing_label", sa.String(100), nullable=False, server_default="Item"),
        sa.Column("listing_label_plural", sa.String(100), nullable=False, server_default="Items"),
        sa.Column(
            "attributes_schema",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("extraction_prompt", sa.Text(), nullable=True),
        sa.Column("file_parse_prompt", sa.Text(), nullable=True),
        sa.Column("insights_prompt", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_unique_constraint("uq_industry_schemas_industry", "industry_schemas", ["industry"])
    op.create_index("ix_industry_schemas_industry", "industry_schemas", ["industry"])

    # ── 2. chatbot_configs — add industry + listing_filter_config, drop allow_rental ──
    op.add_column(
        "chatbot_configs",
        sa.Column(
            "industry",
            sa.String(100),
            nullable=False,
            server_default="real_estate",
        ),
    )
    op.add_column(
        "chatbot_configs",
        sa.Column(
            "listing_filter_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
    )
    op.drop_column("chatbot_configs", "allow_rental")

    # ── 3. listings — major reshape ──────────────────────────────────────────
    # 3a. Drop old RE-specific columns (IF EXISTS avoids aborting the transaction)
    for col in ("listing_type", "bedrooms", "bathrooms", "garages", "land_sqm", "house_sqm", "has_pool"):
        op.execute(f"ALTER TABLE listings DROP COLUMN IF EXISTS {col}")

    # 3b. Drop old RE-specific indexes (IF EXISTS avoids aborting the transaction)
    for idx in (
        "ix_listings_tenant_listing_type",
        "ix_listings_tenant_suburb",
        "ix_listings_tenant_status",
    ):
        op.execute(f"DROP INDEX IF EXISTS {idx}")

    # 3c. Add new generic columns
    op.add_column(
        "listings",
        sa.Column(
            "industry",
            sa.String(100),
            nullable=False,
            server_default="real_estate",
        ),
    )
    op.add_column(
        "listings",
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
    )

    # 3d. Convert status column to plain VARCHAR (drop old PG ENUM if it exists)
    op.execute("ALTER TABLE listings ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TABLE listings ALTER COLUMN status TYPE VARCHAR(50) USING status::text")
    op.execute("DROP TYPE IF EXISTS listing_status CASCADE")

    # 3e. Create new indexes
    op.create_index("ix_listings_tenant_industry", "listings", ["tenant_id", "industry"])
    op.create_index(
        "ix_listings_attributes_gin",
        "listings",
        ["attributes"],
        postgresql_using="gin",
    )

    # ── 4. listing_upload_jobs — add chatbot_config_id + industry ────────────
    op.add_column(
        "listing_upload_jobs",
        sa.Column("chatbot_config_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "listing_upload_jobs",
        sa.Column(
            "industry",
            sa.String(100),
            nullable=False,
            server_default="real_estate",
        ),
    )
    op.create_foreign_key(
        "fk_listing_upload_jobs_chatbot_config",
        "listing_upload_jobs",
        "chatbot_configs",
        ["chatbot_config_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # ── 5. conversation_insights — drop RE columns, add industry_insights JSONB ──
    for col in (
        "budget_min", "budget_max", "budget_currency",
        "suburbs_mentioned", "cities_mentioned", "property_types",
        "bedrooms_wanted", "timeline", "intent",
    ):
        op.execute(f"ALTER TABLE conversation_insights DROP COLUMN IF EXISTS {col}")

    op.add_column(
        "conversation_insights",
        sa.Column(
            "industry",
            sa.String(100),
            nullable=True,
        ),
    )
    op.add_column(
        "conversation_insights",
        sa.Column(
            "industry_insights",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
    )

    # ── 6. Seed starter IndustrySchema rows ──────────────────────────────────
    op.execute("""
        INSERT INTO industry_schemas
            (industry, display_name, listing_label, listing_label_plural, attributes_schema)
        VALUES
        (
            'real_estate',
            'Real Estate',
            'Property',
            'Properties',
            '{"listing_type": {"type": "string", "enum": ["sale", "rent", "lease"]},
              "bedrooms": {"type": "integer"},
              "bathrooms": {"type": "integer"},
              "garages": {"type": "integer"},
              "land_sqm": {"type": "number"},
              "house_sqm": {"type": "number"},
              "has_pool": {"type": "boolean"}}'::jsonb
        ),
        (
            'restaurant',
            'Restaurant / Food',
            'Menu Item',
            'Menu Items',
            '{"category": {"type": "string"},
              "cuisine": {"type": "string"},
              "dietary_tags": {"type": "array", "items": {"type": "string"}},
              "spice_level": {"type": "string"},
              "is_available": {"type": "boolean"}}'::jsonb
        ),
        (
            'ecommerce',
            'E-Commerce / Retail',
            'Product',
            'Products',
            '{"sku": {"type": "string"},
              "brand": {"type": "string"},
              "category": {"type": "string"},
              "stock_quantity": {"type": "integer"},
              "weight_kg": {"type": "number"},
              "variants": {"type": "array"}}'::jsonb
        ),
        (
            'clinic',
            'Health / Clinic',
            'Service',
            'Services',
            '{"service_type": {"type": "string"},
              "duration_minutes": {"type": "integer"},
              "provider": {"type": "string"},
              "bulk_billed": {"type": "boolean"},
              "requires_referral": {"type": "boolean"}}'::jsonb
        )
        ON CONFLICT (industry) DO NOTHING;
    """)


def downgrade() -> None:
    # ── Reverse order ────────────────────────────────────────────────────────

    # 6. Remove seeds (no-op — just leave them or do nothing on downgrade)

    # 5. Restore conversation_insights RE columns
    op.drop_column("conversation_insights", "industry_insights")
    op.drop_column("conversation_insights", "industry")
    op.add_column("conversation_insights", sa.Column("intent", sa.String(100), nullable=True))
    op.add_column("conversation_insights", sa.Column("timeline", sa.String(100), nullable=True))
    op.add_column("conversation_insights", sa.Column("bedrooms_wanted", sa.Integer(), nullable=True))
    op.add_column("conversation_insights", sa.Column("property_types", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("conversation_insights", sa.Column("cities_mentioned", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("conversation_insights", sa.Column("suburbs_mentioned", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("conversation_insights", sa.Column("budget_currency", sa.String(10), nullable=True))
    op.add_column("conversation_insights", sa.Column("budget_max", sa.Numeric(12, 2), nullable=True))
    op.add_column("conversation_insights", sa.Column("budget_min", sa.Numeric(12, 2), nullable=True))

    # 4. Remove listing_upload_jobs additions
    op.drop_constraint("fk_listing_upload_jobs_chatbot_config", "listing_upload_jobs", type_="foreignkey")
    op.drop_column("listing_upload_jobs", "industry")
    op.drop_column("listing_upload_jobs", "chatbot_config_id")

    # 3. Restore listings RE columns
    op.drop_index("ix_listings_attributes_gin", table_name="listings")
    op.drop_index("ix_listings_tenant_industry", table_name="listings")
    op.drop_column("listings", "attributes")
    op.drop_column("listings", "industry")
    op.add_column("listings", sa.Column("has_pool", sa.Boolean(), server_default=sa.text("FALSE"), nullable=False))
    op.add_column("listings", sa.Column("house_sqm", sa.Numeric(10, 2), nullable=True))
    op.add_column("listings", sa.Column("land_sqm", sa.Numeric(10, 2), nullable=True))
    op.add_column("listings", sa.Column("garages", sa.Integer(), nullable=True))
    op.add_column("listings", sa.Column("bathrooms", sa.Integer(), nullable=True))
    op.add_column("listings", sa.Column("bedrooms", sa.Integer(), nullable=True))
    op.add_column("listings", sa.Column("listing_type", sa.String(50), nullable=True))

    # 2. Restore chatbot_configs allow_rental, remove industry + listing_filter_config
    op.drop_column("chatbot_configs", "listing_filter_config")
    op.drop_column("chatbot_configs", "industry")
    op.add_column(
        "chatbot_configs",
        sa.Column("allow_rental", sa.Boolean(), server_default=sa.text("FALSE"), nullable=False),
    )

    # 1. Drop industry_schemas
    op.drop_index("ix_industry_schemas_industry", table_name="industry_schemas")
    op.drop_constraint("uq_industry_schemas_industry", "industry_schemas", type_="unique")
    op.drop_table("industry_schemas")
