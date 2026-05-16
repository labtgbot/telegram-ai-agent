"""Test fixtures.

The DB-backed fixtures require PostgreSQL (we use partitioned tables, JSONB
and partial indexes — SQLite cannot emulate them).  Tests skip cleanly when
``DATABASE_URL`` is not set or the DB is unreachable.
"""
from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


@pytest.fixture(autouse=True)
def _reset_pricing_cache() -> None:
    """Drop the in-process pricing cache before and after every test.

    The cache (issue #36) is module-level and persists across tests in a
    process. Without this reset, a default-config read in one test would
    mask an admin-update flushed by the next test, since the second test
    rolls back the SAVEPOINT but cannot un-cache the value.
    """
    from app.services.pricing import invalidate_pricing_cache

    invalidate_pricing_cache()
    yield
    invalidate_pricing_cache()


def _database_url() -> str | None:
    return os.getenv("DATABASE_URL") or os.getenv("TEST_DATABASE_URL")


async def _can_connect(url: str) -> bool:
    engine = create_async_engine(url, future=True)
    try:
        async with engine.connect() as conn:
            await conn.exec_driver_sql("SELECT 1")
        return True
    except Exception:
        return False
    finally:
        await engine.dispose()


def _run_alembic_upgrade(url: str) -> None:
    """Run ``alembic upgrade head`` against the given URL.

    Imported lazily so ``test_models_structure`` works without alembic
    installed.
    """
    from alembic.config import Config

    from alembic import command

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    os.environ["DATABASE_URL"] = url
    command.upgrade(cfg, "head")


async def _truncate_user_tables(url: str) -> None:
    engine = create_async_engine(url, future=True)
    try:
        async with engine.begin() as conn:
            result = await conn.exec_driver_sql(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
            )
            tables = [row[0] for row in result.fetchall()]
            if tables:
                quoted = ", ".join(f'"{t}"' for t in tables)
                await conn.exec_driver_sql(
                    f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE"
                )
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def database_url() -> str:
    url = _database_url()
    if not url:
        pytest.skip("DATABASE_URL not configured — skipping DB integration tests")
    if not asyncio.run(_can_connect(url)):
        pytest.skip(f"Cannot reach database at {url} — skipping DB integration tests")
    _run_alembic_upgrade(url)
    # The per-test fixture wraps work in a rollback'd transaction, but rows
    # committed before pytest started (e.g. by CI's ``scripts.seed`` step)
    # would leak into aggregate queries. Wipe them once per session.
    asyncio.run(_truncate_user_tables(url))
    return url


@pytest_asyncio.fixture
async def db_engine(database_url: str):
    engine = create_async_engine(database_url, future=True)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncIterator[AsyncSession]:
    """Yield a session that rolls back on teardown.

    Each test sees a clean slate; we run inside a SAVEPOINT-style nested
    transaction and roll the outer one back at the end.
    """
    factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    async with db_engine.connect() as connection:
        outer = await connection.begin()
        session = factory(bind=connection)
        try:
            yield session
        finally:
            await session.close()
            await outer.rollback()
