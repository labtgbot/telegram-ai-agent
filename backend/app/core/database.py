"""Async SQLAlchemy engine and session factory.

The engine is configured with an explicit connection pool sized for the
production workload described in ``docs/PERFORMANCE.md``. Settings come
from :class:`app.core.config.Settings` so a sealed-secret or environment
override can retune the pool without a code change.

``pool_pre_ping`` keeps stale connections out of the pool when the DB
restarts; ``pool_recycle`` retires connections before pgbouncer / managed
PostgreSQL closes them on us. For asyncpg the per-connection statement
cache is sized via ``connect_args`` — the default ``100`` is too small
for our hot prepared-statement set (rate limiter + token service).
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings


def make_engine(database_url: str | None = None):
    settings = get_settings()
    url = database_url or settings.database_url
    connect_args: dict[str, object] = {}
    if "+asyncpg" in url:
        connect_args["statement_cache_size"] = settings.db_statement_cache_size
    return create_async_engine(
        url,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_recycle=settings.db_pool_recycle,
        connect_args=connect_args,
        future=True,
    )


def make_session_factory(engine=None) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=engine or make_engine(),
        expire_on_commit=False,
        autoflush=False,
        class_=AsyncSession,
    )


_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = make_engine()
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = make_session_factory(get_engine())
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    factory = get_session_factory()
    async with factory() as session:
        yield session
