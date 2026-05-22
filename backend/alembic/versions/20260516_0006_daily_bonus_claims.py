"""daily bonus & streak: ledger table for one-claim-per-UTC-day

Revision ID: 0006_daily_bonus_claims
Revises: 0005_chat_history
Create Date: 2026-05-16

Issue #22 adds a daily retention loop.  Streak state is hot enough to
live in Redis (sub-millisecond reads on the "claim" path), but Redis
keys are evictable, so we duplicate every claim into a durable ledger:

* ``daily_bonus_claims`` — one row per ``(user_id, claim_date)``.

The ``UNIQUE(user_id, claim_date)`` constraint is the second line of
defence against double-credit: even if two requests race past the
service-level guard, the second INSERT trips an IntegrityError before
the bonus transaction can be flushed.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_daily_bonus_claims"
down_revision: str | Sequence[str] | None = "0005_chat_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "daily_bonus_claims",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("claim_date", sa.Date(), nullable=False),
        sa.Column("streak_day", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("transaction_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_daily_bonus_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["transactions.id"],
            name="fk_daily_bonus_transaction",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_daily_bonus_claims"),
        sa.UniqueConstraint(
            "user_id", "claim_date", name="uq_daily_bonus_user_date"
        ),
    )
    op.create_index(
        "ix_daily_bonus_user_id",
        "daily_bonus_claims",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_daily_bonus_user_date_desc",
        "daily_bonus_claims",
        ["user_id", "claim_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_daily_bonus_user_date_desc", table_name="daily_bonus_claims"
    )
    op.drop_index("ix_daily_bonus_user_id", table_name="daily_bonus_claims")
    op.drop_table("daily_bonus_claims")
