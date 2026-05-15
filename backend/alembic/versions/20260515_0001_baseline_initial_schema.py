"""baseline initial schema

Создаёт все таблицы Phase 1 (users, transactions, token_usage_logs,
admin_settings, daily_analytics, subscriptions), индексы и партиции
для ``token_usage_logs``.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-05-15

"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001_baseline"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _first_of_month(d: datetime) -> datetime:
    return d.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _next_month(d: datetime) -> datetime:
    """Return the first day of the month after ``d``."""
    return _first_of_month(d.replace(day=28) + timedelta(days=4))


def upgrade() -> None:
    # ---------- users -------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("first_name", sa.String(length=255), nullable=True),
        sa.Column("last_name", sa.String(length=255), nullable=True),
        sa.Column(
            "language_code", sa.String(length=10), nullable=True, server_default="ru"
        ),
        sa.Column("token_balance", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "total_tokens_purchased", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "total_tokens_spent", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("is_premium", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("premium_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_active_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("total_requests", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("referred_by", sa.BigInteger(), nullable=True),
        sa.Column("referral_code", sa.String(length=50), nullable=False),
        sa.Column("is_banned", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("ban_reason", sa.Text(), nullable=True),
        sa.Column("banned_until", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["referred_by"], ["users.id"], name="fk_users_referred_by_users"),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("telegram_id", name="uq_users_telegram_id"),
        sa.UniqueConstraint("referral_code", name="uq_users_referral_code"),
    )
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"], unique=False)
    op.create_index(
        "ix_users_premium",
        "users",
        ["is_premium"],
        unique=False,
        postgresql_where=sa.text("is_premium = TRUE"),
    )
    op.create_index("ix_users_referral", "users", ["referral_code"], unique=False)

    # ---------- transactions ------------------------------------------------
    op.create_table(
        "transactions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("transaction_type", sa.String(length=50), nullable=False),
        sa.Column("tokens_amount", sa.Integer(), nullable=False),
        sa.Column("stars_amount", sa.Integer(), nullable=True),
        sa.Column("usd_amount", sa.Numeric(10, 2), nullable=True),
        sa.Column("package_name", sa.String(length=100), nullable=True),
        sa.Column("discount_percent", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("payment_id", sa.String(length=255), nullable=True),
        sa.Column(
            "payment_status", sa.String(length=50), nullable=True, server_default="pending"
        ),
        sa.Column("payment_method", sa.String(length=50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_transactions_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "transaction_type IN ('purchase','spend','bonus','refund','manual_bonus')",
            name="ck_transactions_transaction_type_allowed",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_transactions"),
    )
    op.create_index(
        "ix_transactions_user_id", "transactions", ["user_id"], unique=False
    )
    op.create_index(
        "ix_transactions_type", "transactions", ["transaction_type"], unique=False
    )
    op.create_index(
        "ix_transactions_created",
        "transactions",
        [sa.text("created_at DESC")],
        unique=False,
    )

    # ---------- token_usage_logs (PARTITIONED) ------------------------------
    # PostgreSQL requires the partition key to be part of every UNIQUE
    # constraint (incl. PK), so the PK is composite ``(id, created_at)``.
    op.execute(
        """
        CREATE TABLE token_usage_logs (
            id                  BIGSERIAL,
            user_id             BIGINT NOT NULL,
            service_type        VARCHAR(100) NOT NULL,
            tokens_consumed     INTEGER NOT NULL,
            request_params      JSONB,
            response_status     VARCHAR(50),
            processing_time_ms  INTEGER,
            composio_tool       VARCHAR(255),
            mcp_server          VARCHAR(255),
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT pk_token_usage_logs PRIMARY KEY (id, created_at),
            CONSTRAINT fk_token_usage_logs_user_id_users
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        ) PARTITION BY RANGE (created_at);
        """
    )
    op.create_index(
        "ix_token_usage_logs_user_id",
        "token_usage_logs",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_token_usage_logs_service",
        "token_usage_logs",
        ["service_type"],
        unique=False,
    )
    op.create_index(
        "ix_token_usage_logs_created",
        "token_usage_logs",
        [sa.text("created_at DESC")],
        unique=False,
    )

    # Стартовые партиции: текущий и следующий месяц.  Дальнейшую ротацию
    # выполняет ежемесячный Celery beat job (см. ADR-0005 §Partitioning).
    now_utc = datetime.now(UTC)
    current = _first_of_month(now_utc)
    nxt = _next_month(current)
    after_next = _next_month(nxt)

    for start, end in ((current, nxt), (nxt, after_next)):
        op.execute(
            f"""
            CREATE TABLE token_usage_logs_{start.strftime("%Y_%m")}
            PARTITION OF token_usage_logs
            FOR VALUES FROM ('{start.isoformat()}') TO ('{end.isoformat()}');
            """
        )

    # ---------- admin_settings ---------------------------------------------
    op.create_table(
        "admin_settings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("setting_key", sa.String(length=100), nullable=False),
        sa.Column("setting_value", postgresql.JSONB(), nullable=False),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_admin_settings"),
        sa.UniqueConstraint("setting_key", name="uq_admin_settings_setting_key"),
    )

    # ---------- daily_analytics --------------------------------------------
    op.create_table(
        "daily_analytics",
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("total_users", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("new_users", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active_users", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("premium_users", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "total_tokens_sold", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "total_stars_revenue", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "total_usd_revenue", sa.Numeric(12, 2), nullable=False, server_default="0"
        ),
        sa.Column("total_requests", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "image_generations", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "video_generations", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("text_queries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("avg_tokens_per_user", sa.Numeric(10, 2), nullable=True),
        sa.Column("conversion_rate", sa.Numeric(5, 2), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("date", name="pk_daily_analytics"),
    )

    # ---------- subscriptions ----------------------------------------------
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("plan_code", sa.String(length=50), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("auto_renew", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_transaction_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="active"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_subscriptions_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["last_transaction_id"],
            ["transactions.id"],
            name="fk_subscriptions_last_transaction_id_transactions",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_subscriptions"),
    )
    op.create_index("ix_subscriptions_user", "subscriptions", ["user_id"], unique=False)


def downgrade() -> None:
    # Drop subscriptions first (depends on transactions / users).
    op.drop_index("ix_subscriptions_user", table_name="subscriptions")
    op.drop_table("subscriptions")

    op.drop_table("daily_analytics")
    op.drop_table("admin_settings")

    # token_usage_logs and its partitions
    op.drop_index("ix_token_usage_logs_created", table_name="token_usage_logs")
    op.drop_index("ix_token_usage_logs_service", table_name="token_usage_logs")
    op.drop_index("ix_token_usage_logs_user_id", table_name="token_usage_logs")
    # CASCADE removes every partition in one shot.
    op.execute("DROP TABLE token_usage_logs CASCADE;")

    op.drop_index("ix_transactions_created", table_name="transactions")
    op.drop_index("ix_transactions_type", table_name="transactions")
    op.drop_index("ix_transactions_user_id", table_name="transactions")
    op.drop_table("transactions")

    op.drop_index("ix_users_referral", table_name="users")
    op.drop_index("ix_users_premium", table_name="users")
    op.drop_index("ix_users_telegram_id", table_name="users")
    op.drop_table("users")
