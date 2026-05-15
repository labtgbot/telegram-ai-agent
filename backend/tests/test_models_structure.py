"""Pure-introspection checks: model classes match the documented schema.

Runs without a database — guards the contract between models and
``docs/DATABASE_SCHEMA.md``.
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Integer  # noqa: E402

from app.models import (  # noqa: E402
    AdminSetting,
    Base,
    DailyAnalytics,
    Subscription,
    TokenUsageLog,
    Transaction,
    User,
)


def test_all_tables_registered():
    expected = {
        "users",
        "transactions",
        "token_usage_logs",
        "admin_settings",
        "daily_analytics",
        "subscriptions",
    }
    assert expected.issubset(set(Base.metadata.tables.keys()))


def test_user_columns_and_constraints():
    table = User.__table__
    expected_columns = {
        "id",
        "telegram_id",
        "username",
        "first_name",
        "last_name",
        "language_code",
        "token_balance",
        "total_tokens_purchased",
        "total_tokens_spent",
        "is_premium",
        "premium_expires_at",
        "created_at",
        "last_active_at",
        "total_requests",
        "referred_by",
        "referral_code",
        "is_banned",
        "ban_reason",
        "banned_until",
        "role",
        "totp_secret",
        "totp_enabled",
        "last_login_at",
    }
    assert expected_columns == set(table.columns.keys())

    assert isinstance(table.c.id.type, BigInteger)
    assert isinstance(table.c.telegram_id.type, BigInteger)
    assert table.c.telegram_id.unique is True
    assert table.c.referral_code.unique is True
    assert isinstance(table.c.is_premium.type, Boolean)
    assert isinstance(table.c.created_at.type, DateTime)
    assert table.c.created_at.type.timezone is True


def test_user_indexes_present():
    index_names = {ix.name for ix in User.__table__.indexes}
    assert "ix_users_telegram_id" in index_names
    assert "ix_users_premium" in index_names
    assert "ix_users_referral" in index_names

    premium_index = next(ix for ix in User.__table__.indexes if ix.name == "ix_users_premium")
    where_clause = premium_index.dialect_options["postgresql"].get("where")
    assert where_clause == "is_premium = TRUE"


def test_transaction_check_constraint():
    constraints = [
        c for c in Transaction.__table__.constraints if isinstance(c, CheckConstraint)
    ]
    assert constraints, "transactions table must have a CHECK constraint"
    assert any("purchase" in str(c.sqltext) for c in constraints)
    assert any("manual_bonus" in str(c.sqltext) for c in constraints)


def test_transaction_indexes_present():
    index_names = {ix.name for ix in Transaction.__table__.indexes}
    assert {"ix_transactions_user_id", "ix_transactions_type", "ix_transactions_created"} <= index_names


def test_token_usage_log_is_partitioned():
    args = TokenUsageLog.__table__.dialect_options["postgresql"]
    assert args.get("partition_by") == "RANGE (created_at)"

    # Composite primary key (id, created_at) — required by Postgres for partitioned tables.
    pk_columns = {c.name for c in TokenUsageLog.__table__.primary_key.columns}
    assert pk_columns == {"id", "created_at"}


def test_admin_setting_columns():
    cols = AdminSetting.__table__.columns
    assert {"id", "setting_key", "setting_value", "updated_by", "updated_at"} == set(cols.keys())
    assert isinstance(cols["id"].type, Integer)
    assert cols["setting_key"].unique is True


def test_daily_analytics_primary_key_is_date():
    pk_cols = {c.name for c in DailyAnalytics.__table__.primary_key.columns}
    assert pk_cols == {"date"}


def test_subscription_foreign_keys():
    fks = {fk.column.table.name for fk in Subscription.__table__.foreign_keys}
    assert {"users", "transactions"} <= fks
