"""add_billing_tables

Revision ID: 52c7af1fddad
Revises: 8a3a4141ea8b
Create Date: 2026-04-09 13:21:43.444365

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '52c7af1fddad'
down_revision: Union[str, None] = '8a3a4141ea8b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('addons',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('slug', sa.String(length=100), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('type', sa.Enum('extra_users', 'extra_conversations', 'extra_storage', 'premium_widget', name='addon_type'), nullable=False),
    sa.Column('price_aud_cents', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('price_usd_cents', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('stripe_price_id', sa.String(length=255), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('TRUE'), nullable=False),
    sa.Column('public_id', sa.String(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('slug')
    )
    op.create_index(op.f('ix_addons_public_id'), 'addons', ['public_id'], unique=True)
    op.create_index('ix_addons_slug', 'addons', ['slug'], unique=False)
    op.create_index('ix_addons_type_active', 'addons', ['type'], unique=False, postgresql_where=sa.text('is_active = TRUE'))

    op.create_table('plans',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('slug', sa.String(length=100), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('billing_interval', sa.Enum('monthly', 'annual', name='billing_interval'), server_default=sa.text("'monthly'"), nullable=False),
    sa.Column('price_aud_cents', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('price_usd_cents', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('limits', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('stripe_monthly_price_id', sa.String(length=255), nullable=True),
    sa.Column('stripe_annual_price_id', sa.String(length=255), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('TRUE'), nullable=False),
    sa.Column('is_public', sa.Boolean(), server_default=sa.text('TRUE'), nullable=False),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('public_id', sa.String(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('slug')
    )
    op.create_index('ix_plans_active_public', 'plans', ['is_active', 'is_public', 'sort_order'], unique=False)
    op.create_index(op.f('ix_plans_public_id'), 'plans', ['public_id'], unique=True)
    op.create_index('ix_plans_slug', 'plans', ['slug'], unique=False)

    op.create_table('tenant_subscriptions',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('tenant_id', sa.BigInteger(), nullable=False),
    sa.Column('plan_id', sa.BigInteger(), nullable=False),
    sa.Column('status', sa.Enum('trialing', 'active', 'past_due', 'cancelled', 'paused', name='subscription_status'), server_default=sa.text("'trialing'"), nullable=False),
    sa.Column('currency', sa.String(length=3), server_default=sa.text("'AUD'"), nullable=False),
    sa.Column('current_period_start', sa.DateTime(timezone=True), nullable=True),
    sa.Column('current_period_end', sa.DateTime(timezone=True), nullable=True),
    sa.Column('trial_ends_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancel_at_period_end', sa.Boolean(), server_default=sa.text('FALSE'), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('stripe_subscription_id', sa.String(length=255), nullable=True),
    sa.Column('stripe_customer_id', sa.String(length=255), nullable=True),
    sa.Column('public_id', sa.String(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
    sa.ForeignKeyConstraint(['plan_id'], ['plans.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('stripe_subscription_id')
    )
    op.create_index('ix_tenant_subs_status', 'tenant_subscriptions', ['status'], unique=False)
    op.create_index('ix_tenant_subs_stripe', 'tenant_subscriptions', ['stripe_subscription_id'], unique=False)
    op.create_index('ix_tenant_subs_tenant', 'tenant_subscriptions', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_tenant_subscriptions_public_id'), 'tenant_subscriptions', ['public_id'], unique=True)

    op.create_table('usage_records',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('tenant_id', sa.BigInteger(), nullable=False),
    sa.Column('metric', sa.Enum('conversations', 'messages', 'tokens_used', 'pages_crawled', 'documents_uploaded', 'active_users', name='usage_metric'), nullable=False),
    sa.Column('quantity', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('period_month', sa.String(length=7), nullable=False),
    sa.Column('warned_80', sa.Boolean(), server_default=sa.text('FALSE'), nullable=False),
    sa.Column('warned_90', sa.Boolean(), server_default=sa.text('FALSE'), nullable=False),
    sa.Column('recorded_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'metric', 'period_month', name='uq_usage_tenant_metric_month')
    )
    op.create_index('ix_usage_metric_period', 'usage_records', ['metric', 'period_month'], unique=False)
    op.create_index('ix_usage_tenant_period', 'usage_records', ['tenant_id', 'period_month'], unique=False)

    op.create_table('tenant_addon_subscriptions',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('tenant_id', sa.BigInteger(), nullable=False),
    sa.Column('addon_id', sa.BigInteger(), nullable=False),
    sa.Column('subscription_id', sa.BigInteger(), nullable=True),
    sa.Column('status', sa.Enum('trialing', 'active', 'past_due', 'cancelled', 'paused', name='subscription_status'), server_default=sa.text("'active'"), nullable=False),
    sa.Column('quantity', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('currency', sa.String(length=3), server_default=sa.text("'AUD'"), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('stripe_subscription_item_id', sa.String(length=255), nullable=True),
    sa.Column('public_id', sa.String(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
    sa.ForeignKeyConstraint(['addon_id'], ['addons.id'], ),
    sa.ForeignKeyConstraint(['subscription_id'], ['tenant_subscriptions.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'addon_id', name='uq_tenant_addon')
    )
    op.create_index('ix_tenant_addon_subs_status', 'tenant_addon_subscriptions', ['tenant_id', 'status'], unique=False)
    op.create_index('ix_tenant_addon_subs_tenant', 'tenant_addon_subscriptions', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_tenant_addon_subscriptions_public_id'), 'tenant_addon_subscriptions', ['public_id'], unique=True)

    op.drop_index('ix_tenants_public_id', table_name='tenants')
    op.create_index('ix_tenants_public_id', 'tenants', ['public_id'], unique=False)
    op.drop_index('ix_users_public_id', table_name='users')
    op.create_index('ix_users_public_id', 'users', ['public_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_users_public_id', table_name='users')
    op.create_index('ix_users_public_id', 'users', ['public_id'], unique=True)
    op.drop_index('ix_tenants_public_id', table_name='tenants')
    op.create_index('ix_tenants_public_id', 'tenants', ['public_id'], unique=True)
    op.drop_index(op.f('ix_tenant_addon_subscriptions_public_id'), table_name='tenant_addon_subscriptions')
    op.drop_index('ix_tenant_addon_subs_tenant', table_name='tenant_addon_subscriptions')
    op.drop_index('ix_tenant_addon_subs_status', table_name='tenant_addon_subscriptions')
    op.drop_table('tenant_addon_subscriptions')
    op.drop_index('ix_usage_tenant_period', table_name='usage_records')
    op.drop_index('ix_usage_metric_period', table_name='usage_records')
    op.drop_table('usage_records')
    op.drop_index(op.f('ix_tenant_subscriptions_public_id'), table_name='tenant_subscriptions')
    op.drop_index('ix_tenant_subs_tenant', table_name='tenant_subscriptions')
    op.drop_index('ix_tenant_subs_stripe', table_name='tenant_subscriptions')
    op.drop_index('ix_tenant_subs_status', table_name='tenant_subscriptions')
    op.drop_table('tenant_subscriptions')
    op.drop_index('ix_plans_slug', table_name='plans')
    op.drop_index(op.f('ix_plans_public_id'), table_name='plans')
    op.drop_index('ix_plans_active_public', table_name='plans')
    op.drop_table('plans')
    op.drop_index('ix_addons_type_active', table_name='addons', postgresql_where=sa.text('is_active = TRUE'))
    op.drop_index('ix_addons_slug', table_name='addons')
    op.drop_index(op.f('ix_addons_public_id'), table_name='addons')
    op.drop_table('addons')
    op.execute('DROP TYPE IF EXISTS usage_metric')
    op.execute('DROP TYPE IF EXISTS subscription_status')
    op.execute('DROP TYPE IF EXISTS billing_interval')
    op.execute('DROP TYPE IF EXISTS addon_type')