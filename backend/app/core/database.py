"""Async SQLAlchemy engine and session factory."""
from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings


def make_engine(database_url: str | None = None):
    url = database_url or get_settings().database_url
    return create_async_engine(url, pool_pre_ping=True, future=True)


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
