import os
from sqlalchemy.pool import NullPool
from sqlalchemy import create_engine
from app.core.db_base import Base
from app.modules.chat.models import Conversation, Message, ConversationInsights
from app.modules.inquiries.models import GeneralInquiry, DemoInquiry, AffiliationInquiry
from app.modules.chatbot.models import ChatbotConfig, WidgetTheme, KnowledgeSource, CrawlJob, Document, DocumentChunk, Listing, ChatbotAsset, ListingUploadJob
from app.modules.users.models import User
from app.modules.models.otp import OTPVerification
from app.modules.models.tenant_user import TenantUser
from app.modules.tenants.models import Tenant
from app.modules.billing.models import Plan, Addon, TenantSubscription, TenantAddonSubscription, UsageRecord
from logging.config import fileConfig
from sqlalchemy import pool
from alembic import context
from app.config.settings import get_settings
settings = get_settings()


# ✅ Always use DATABASE_URL from environment directly
def get_sync_db_url() -> str:
    url = settings.DATABASE_URL
    if not url:
        raise RuntimeError("DATABASE_URL environment variable is not set")
    # Convert to sync psycopg2 driver for alembic (not asyncpg)
    url = url.replace("postgres://", "postgresql://", 1)
    url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return url

DATABASE_URL = get_sync_db_url()

config = context.config
config.set_main_option("sqlalchemy.url", DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # ✅ Use create_engine directly with ssl for Heroku
    is_dev = settings.ENV == "DEVELOPMENT"
    connect_args = {} if is_dev else {"sslmode": "require"}

    connectable = create_engine(
        DATABASE_URL,
        poolclass=NullPool,  # NullPool is best for migrations
        connect_args=connect_args,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()