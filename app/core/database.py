from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.config.settings import get_settings
from contextlib import asynccontextmanager

settings = get_settings()

# -----------------------------
# DATABASE URL TRANSFORMATION
# -----------------------------


def build_async_db_url() -> str:
    raw_url = settings.DATABASE_URL

    if not raw_url:
        raise RuntimeError("DATABASE_URL is not set")

    # Heroku provides: postgres://
    if raw_url.startswith("postgres://"):
        raw_url = raw_url.replace(
            "postgres://",
            "postgresql+asyncpg://",
            1,
        )

    return raw_url


DATABASE_URL = build_async_db_url()



# Module-level engine — ONLY for FastAPI routes (shares FastAPI's event loop)
connect_args = {}
if settings.ENV != "DEVELOPMENT":
    connect_args = {"ssl": True}
async_engine = create_async_engine(
    DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    connect_args=connect_args,
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    expire_on_commit=False,
    class_=AsyncSession,
)

# ✅ For FastAPI routes — reuses module-level engine (correct)
async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()  # commits all changes at end of request
        except Exception:
            await session.rollback()
            raise

# ✅ For Celery tasks — creates fresh engine per task (correct)
@asynccontextmanager
async def get_task_db_session():
    engine = create_async_engine(
        DATABASE_URL,
        pool_size=2,        # Small — each task is short-lived
        max_overflow=3,
        pool_pre_ping=True,
        pool_recycle=60,
        connect_args={"ssl": False} if settings.ENV == "DEVELOPMENT" else {"ssl": True},
    )
    try:
        factory = async_sessionmaker(
            bind=engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )
        async with factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()
    finally:
        await engine.dispose()  # Close all connections when task finishes