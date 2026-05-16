"""broadcasts: campaign + per-recipient delivery rows

Revision ID: 0008_broadcasts
Revises: 0007_admin_audit_logs
Create Date: 2026-05-16

Issue #28 introduces the Broadcast Messaging section of the admin CRM.
Admins compose a campaign (text / media / inline buttons) for a target
audience and a Celery worker drains the recipient queue while honouring
Telegram's 30 msg/sec limit.  Two tables back the feature:

* ``broadcasts`` — campaign metadata + running counters.
* ``broadcast_recipients`` — per-recipient row written by the worker
  with the Telegram ``message_id`` (when delivered) or the error.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008_broadcasts"
down_revision: str | Sequence[str] | None = "0007_admin_audit_logs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "broadcasts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "parse_mode",
            sa.String(length=16),
            nullable=True,
            server_default="HTML",
        ),
        sa.Column("media_type", sa.String(length=16), nullable=True),
        sa.Column("media_url", sa.Text(), nullable=True),
        sa.Column(
            "buttons",
            sa.dialects.postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("audience", sa.String(length=32), nullable=False),
        sa.Column(
            "audience_filter",
            sa.dialects.postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_recipients", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sent_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("delivered_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("clicks_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_broadcasts_created_by",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_broadcasts"),
    )
    op.create_index("ix_broadcasts_status", "broadcasts", ["status"], unique=False)
    op.create_index("ix_broadcasts_scheduled_at", "broadcasts", ["scheduled_at"], unique=False)
    op.create_index("ix_broadcasts_created_by", "broadcasts", ["created_by"], unique=False)
    op.create_index("ix_broadcasts_created_at", "broadcasts", ["created_at"], unique=False)

    op.create_table(
        "broadcast_recipients",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("broadcast_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("clicks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["broadcast_id"],
            ["broadcasts.id"],
            name="fk_broadcast_recipients_broadcast_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_broadcast_recipients_user_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "broadcast_id",
            "user_id",
            name="uq_broadcast_recipients_broadcast_id",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_broadcast_recipients"),
    )
    op.create_index(
        "ix_broadcast_recipients_broadcast_id",
        "broadcast_recipients",
        ["broadcast_id"],
        unique=False,
    )
    op.create_index(
        "ix_broadcast_recipients_status",
        "broadcast_recipients",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_broadcast_recipients_user_id",
        "broadcast_recipients",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_broadcast_recipients_user_id", table_name="broadcast_recipients")
    op.drop_index("ix_broadcast_recipients_status", table_name="broadcast_recipients")
    op.drop_index("ix_broadcast_recipients_broadcast_id", table_name="broadcast_recipients")
    op.drop_table("broadcast_recipients")

    op.drop_index("ix_broadcasts_created_at", table_name="broadcasts")
    op.drop_index("ix_broadcasts_created_by", table_name="broadcasts")
    op.drop_index("ix_broadcasts_scheduled_at", table_name="broadcasts")
    op.drop_index("ix_broadcasts_status", table_name="broadcasts")
    op.drop_table("broadcasts")
