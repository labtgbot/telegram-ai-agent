"""Alembic environment with async engine support.

Reads the database URL from the ``DATABASE_URL`` env var (with a sensible
local default), falling back to ``alembic.ini`` only as a last resort.
"""

from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Make ``app.*`` importable when running ``alembic`` from the ``backend/`` dir.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.alembic_autogenerate import include_name, include_object  # noqa: E402
from app.models import Base  # noqa: E402  (after sys.path tweak)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _get_url() -> str:
    env_url = os.getenv("DATABASE_URL")
    if env_url:
        return env_url
    cfg_url = config.get_main_option("sqlalchemy.url")
    if not cfg_url:
        raise RuntimeError("DATABASE_URL is not set and alembic.ini has no sqlalchemy.url")
    return cfg_url


def run_migrations_offline() -> None:
    """Render SQL without a live DB connection."""
    url = _get_url()
    # Offline mode does not need async driver; normalize to psycopg/sync.
    sync_url = url.replace("+asyncpg", "+psycopg")
    context.configure(
        url=sync_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_name=include_name,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_name=include_name,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations() -> None:
    cfg = config.get_section(config.config_ini_section, {})
    cfg["sqlalchemy.url"] = _get_url()
    connectable = async_engine_from_config(
        cfg,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(_run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
