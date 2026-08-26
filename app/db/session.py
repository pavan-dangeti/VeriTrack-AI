"""Async SQLAlchemy engine/session management."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
TestingSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, expire_on_commit=False
)


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return _session_factory


def fresh_engine_and_factory():
    """Dedicated engine for out-of-request contexts (Celery tasks).

    Each task gets its own engine so asyncpg connections are always bound to
    the loop actually executing them — under real workers and under eager
    mode alike.
    """
    eng = create_async_engine(settings.database_url, pool_pre_ping=True)
    return eng, async_sessionmaker(eng, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession]:
    async with _session_factory() as session:
        yield session
