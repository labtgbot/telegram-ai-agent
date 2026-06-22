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

from sqlalchemy import (  # noqa: E402
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    UniqueConstraint,
    create_mock_engine,
)

from app.models import (  # noqa: E402
    AccountDeletionRequest,
    AdminRefreshSession,
    AdminSetting,
    Base,
    ChatMessage,
    ChatThread,
    DailyAnalytics,
    Subscription,
    TokenUsageLog,
    Transaction,
    User,
    WelcomeMessage,
)


def test_all_tables_registered():
    expected = {
        "users",
        "transactions",
        "token_usage_logs",
        "admin_settings",
        "admin_refresh_sessions",
        "daily_analytics",
        "subscriptions",
        "account_deletion_requests",
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
        "last_totp_timecode",
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
    assert "ix_users_premium" in index_names
    assert "ix_users_role" in index_names
    assert "ix_users_telegram_id" not in index_names
    assert "ix_users_referral" not in index_names

    premium_index = next(ix for ix in User.__table__.indexes if ix.name == "ix_users_premium")
    where_clause = premium_index.dialect_options["postgresql"].get("where")
    assert where_clause == "is_premium = TRUE"


def test_transaction_check_constraint():
    constraints = [c for c in Transaction.__table__.constraints if isinstance(c, CheckConstraint)]
    assert constraints, "transactions table must have a CHECK constraint"
    assert any("purchase" in str(c.sqltext) for c in constraints)
    assert any("manual_bonus" in str(c.sqltext) for c in constraints)


def test_transaction_indexes_present():
    index_names = {ix.name for ix in Transaction.__table__.indexes}
    assert {
        "ix_transactions_user_id",
        "ix_transactions_type",
        "ix_transactions_created",
        "uq_transactions_payment_id",
        "ix_transactions_payment_status",
    } <= index_names


def test_chat_message_user_id_matches_thread_owner_constraint():
    thread_constraints = {
        constraint.name: constraint
        for constraint in ChatThread.__table__.constraints
    }
    assert isinstance(
        thread_constraints.get("uq_chat_threads_id_user_id"),
        UniqueConstraint,
    )

    message_constraints = {
        constraint.name: constraint
        for constraint in ChatMessage.__table__.constraints
    }
    thread_user_fk = message_constraints.get("fk_chat_messages_thread_user")
    assert isinstance(thread_user_fk, ForeignKeyConstraint)
    assert [element.parent.name for element in thread_user_fk.elements] == [
        "thread_id",
        "user_id",
    ]
    assert [element.column.table.name for element in thread_user_fk.elements] == [
        "chat_threads",
        "chat_threads",
    ]
    assert [element.column.name for element in thread_user_fk.elements] == [
        "id",
        "user_id",
    ]


def test_model_create_all_emits_migration_aligned_indexes():
    statements: list[str] = []

    def capture(sql, *multiparams, **params) -> None:
        statements.append(str(sql.compile(dialect=engine.dialect)))

    engine = create_mock_engine("postgresql://", capture)
    Base.metadata.create_all(engine)

    ddl = "\n".join(statements)
    assert (
        "CREATE UNIQUE INDEX uq_transactions_payment_id "
        "ON transactions (payment_id) WHERE payment_id IS NOT NULL"
    ) in ddl
    assert "CREATE INDEX ix_transactions_payment_status ON transactions (payment_status)" in ddl
    assert "CREATE INDEX ix_transactions_created ON transactions (created_at DESC)" in ddl
    assert ("CREATE INDEX ix_token_usage_logs_created ON token_usage_logs (created_at DESC)") in ddl
    assert (
        "CREATE UNIQUE INDEX uq_welcome_messages_active_per_locale "
        "ON welcome_messages (locale) WHERE is_active"
    ) in ddl


def test_welcome_message_indexes_present():
    index_names = {ix.name for ix in WelcomeMessage.__table__.indexes}
    assert {
        "ix_welcome_messages_locale",
        "ix_welcome_messages_is_active",
        "uq_welcome_messages_active_per_locale",
    } <= index_names


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


def test_admin_setting_updated_by_references_user_with_set_null():
    foreign_keys = AdminSetting.__table__.c.updated_by.foreign_keys

    assert len(foreign_keys) == 1
    fk = next(iter(foreign_keys))
    assert fk.target_fullname == "users.id"
    assert fk.ondelete == "SET NULL"


def test_admin_refresh_session_columns_and_indexes():
    table = AdminRefreshSession.__table__
    assert {
        "id",
        "user_id",
        "jti_hash",
        "role",
        "issued_at",
        "expires_at",
        "used_at",
        "revoked_at",
        "revocation_reason",
        "parent_session_id",
        "replaced_by_session_id",
        "created_at",
    } == set(table.columns.keys())
    assert isinstance(table.c.id.type, BigInteger)
    assert isinstance(table.c.user_id.type, BigInteger)
    assert table.c.jti_hash.unique is True
    assert isinstance(table.c.issued_at.type, DateTime)
    assert table.c.issued_at.type.timezone is True

    index_names = {ix.name for ix in table.indexes}
    assert {
        "ix_admin_refresh_sessions_user_id",
        "ix_admin_refresh_sessions_expires_at",
        "ix_admin_refresh_sessions_parent",
        "ix_admin_refresh_sessions_replaced_by",
    } <= index_names


def test_daily_analytics_primary_key_is_date():
    pk_cols = {c.name for c in DailyAnalytics.__table__.primary_key.columns}
    assert pk_cols == {"date"}


def test_subscription_foreign_keys():
    fks = {fk.column.table.name for fk in Subscription.__table__.foreign_keys}
    assert {"users", "transactions"} <= fks


def test_account_deletion_request_columns():
    table = AccountDeletionRequest.__table__
    expected_columns = {
        "id",
        "user_id",
        "status",
        "requested_at",
        "scheduled_for",
        "cancelled_at",
        "completed_at",
        "failed_at",
        "requested_via",
        "reason",
        "failure_reason",
    }
    assert expected_columns == set(table.columns.keys())
    assert isinstance(table.c.id.type, BigInteger)
    assert isinstance(table.c.requested_at.type, DateTime)
    assert table.c.requested_at.type.timezone is True
    assert isinstance(table.c.failed_at.type, DateTime)
    assert table.c.failed_at.type.timezone is True

    index_names = {ix.name for ix in table.indexes}
    assert {"ix_account_deletion_pending", "uq_account_deletion_active"} <= index_names
