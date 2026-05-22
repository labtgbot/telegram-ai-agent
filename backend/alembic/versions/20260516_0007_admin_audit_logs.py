"""admin audit logs: durable record of every privileged action

Revision ID: 0007_admin_audit_logs
Revises: 0006_daily_bonus_claims
Create Date: 2026-05-16

Issue #25 introduces the User Management section of the admin CRM.  Every
mutation (ban, unban, manual token grant, broadcast-to-user, …) must be
captured to a tamper-evident audit log so support engineers can later
explain *why* a user's state changed.  Rows are append-only — there are
no UPDATE / DELETE code paths.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007_admin_audit_logs"
down_revision: str | Sequence[str] | None = "0006_daily_bonus_claims"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admin_audit_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("admin_id", sa.BigInteger(), nullable=False),
        sa.Column("target_user_id", sa.BigInteger(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column(
            "payload",
            sa.dialects.postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["admin_id"],
            ["users.id"],
            name="fk_admin_audit_admin",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_user_id"],
            ["users.id"],
            name="fk_admin_audit_target",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_admin_audit_logs"),
    )
    op.create_index(
        "ix_admin_audit_admin", "admin_audit_logs", ["admin_id"], unique=False
    )
    op.create_index(
        "ix_admin_audit_target",
        "admin_audit_logs",
        ["target_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_admin_audit_action", "admin_audit_logs", ["action"], unique=False
    )
    op.create_index(
        "ix_admin_audit_created",
        "admin_audit_logs",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_admin_audit_created", table_name="admin_audit_logs")
    op.drop_index("ix_admin_audit_action", table_name="admin_audit_logs")
    op.drop_index("ix_admin_audit_target", table_name="admin_audit_logs")
    op.drop_index("ix_admin_audit_admin", table_name="admin_audit_logs")
    op.drop_table("admin_audit_logs")
