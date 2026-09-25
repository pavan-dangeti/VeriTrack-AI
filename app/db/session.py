from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings


def _engine_kwargs() -> dict:
    return {
        "pool_pre_ping": True,
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
        "pool_timeout": settings.db_pool_timeout,
        "pool_recycle": 1800,  # managed PG/proxies drop idle conns
    }


engine = create_async_engine(settings.database_url, **_engine_kwargs())

_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, expire_on_commit=False
)


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return _session_factory


def fresh_engine_and_factory():
    """Dedicated engine per Celery task so asyncpg connections bind to the loop running them."""
    eng = create_async_engine(settings.database_url, pool_pre_ping=True, pool_size=2,
                              max_overflow=2)
    return eng, async_sessionmaker(eng, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession]:
    async with _session_factory() as session:
        yield session
