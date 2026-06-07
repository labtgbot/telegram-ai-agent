"""Verify that the baseline migration is reversible.

Runs ``upgrade head → downgrade base → upgrade head`` against the configured
database.  Skipped automatically when no ``DATABASE_URL`` is configured.

These tests are intentionally synchronous: ``alembic.command.upgrade`` runs
its own ``asyncio.run`` (see ``alembic/env.py``), which conflicts with the
event loop pytest-asyncio sets up for async tests.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text

from alembic import command

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    os.environ["DATABASE_URL"] = url
    return cfg


def _sync_url(url: str) -> str:
    return url.replace("+asyncpg", "+psycopg")


EXPECTED_TABLES = {
    "users",
    "transactions",
    "token_usage_logs",
    "admin_settings",
    "daily_analytics",
    "subscriptions",
}


def test_upgrade_downgrade_upgrade(database_url):
    """Full reversibility check: schema must be cleanly re-buildable."""
    cfg = _alembic_config(database_url)
    command.downgrade(cfg, "base")

    engine = create_engine(_sync_url(database_url), future=True)
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = ANY(:names)"
            ),
            {"names": list(EXPECTED_TABLES)},
        )
        remaining = {row[0] for row in result.fetchall()}
    engine.dispose()
    assert remaining == set(), f"Tables left after downgrade: {remaining}"

    command.upgrade(cfg, "head")

    engine = create_engine(_sync_url(database_url), future=True)
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = ANY(:names)"
            ),
            {"names": list(EXPECTED_TABLES)},
        )
        present = {row[0] for row in result.fetchall()}
    engine.dispose()
    assert present == EXPECTED_TABLES


def test_partitions_exist_after_upgrade(database_url):
    engine = create_engine(_sync_url(database_url), future=True)
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT count(*) FROM pg_inherits "
                "WHERE inhparent = 'token_usage_logs'::regclass"
            )
        )
        partition_count = result.scalar_one()
    engine.dispose()
    assert partition_count >= 2, (
        f"Expected at least 2 monthly partitions, got {partition_count}"
    )


def test_default_partition_exists_after_upgrade(database_url):
    engine = create_engine(_sync_url(database_url), future=True)
    with engine.connect() as conn:
        result = conn.execute(
            text(
                """
                SELECT count(*)
                FROM pg_inherits
                JOIN pg_class child ON child.oid = pg_inherits.inhrelid
                WHERE inhparent = 'token_usage_logs'::regclass
                  AND pg_get_expr(child.relpartbound, child.oid) = 'DEFAULT'
                """
            )
        )
        default_count = result.scalar_one()
    engine.dispose()
    assert default_count == 1


@pytest.mark.parametrize(
    "index_name",
    [
        "ix_users_telegram_id",
        "ix_users_premium",
        "ix_users_referral",
        "ix_transactions_user_id",
        "ix_transactions_type",
        "ix_transactions_created",
        "ix_token_usage_logs_user_id",
        "ix_token_usage_logs_service",
        "ix_token_usage_logs_created",
        "ix_subscriptions_user",
    ],
)
def test_index_exists(database_url, index_name):
    engine = create_engine(_sync_url(database_url), future=True)
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT count(*) FROM pg_indexes "
                "WHERE schemaname = 'public' AND indexname = :name"
            ),
            {"name": index_name},
        )
        count = result.scalar_one()
    engine.dispose()
    assert count == 1, f"Missing index: {index_name}"
