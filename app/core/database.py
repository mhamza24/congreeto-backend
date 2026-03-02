from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.config.settings import get_settings
from contextlib import asynccontextmanager

settings = get_settings()

# Module-level engine — ONLY for FastAPI routes (shares FastAPI's event loop)
async_engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    expire_on_commit=False,
    class_=AsyncSession,
)

# ✅ For FastAPI routes — reuses module-level engine (correct)
async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session

# ✅ For Celery tasks — creates fresh engine per task (correct)
@asynccontextmanager
async def get_task_db_session():
    engine = create_async_engine(
        settings.DATABASE_URL,
        pool_size=2,        # Small — each task is short-lived
        max_overflow=3,
        pool_pre_ping=True,
        pool_recycle=60,
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