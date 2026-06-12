"""add admin refresh sessions

Revision ID: 0015_admin_refresh_sessions
Revises: 0014_drop_redundant_user_indexes
Create Date: 2026-06-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015_admin_refresh_sessions"
down_revision: str | Sequence[str] | None = "0014_drop_redundant_user_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admin_refresh_sessions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("jti_hash", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.String(length=64), nullable=True),
        sa.Column("parent_session_id", sa.BigInteger(), nullable=True),
        sa.Column("replaced_by_session_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["parent_session_id"],
            ["admin_refresh_sessions.id"],
            name=op.f("fk_admin_refresh_sessions_parent_session_id_admin_refresh_sessions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["replaced_by_session_id"],
            ["admin_refresh_sessions.id"],
            name=op.f("fk_admin_refresh_sessions_replaced_by_session_id_admin_refresh_sessions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_admin_refresh_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_refresh_sessions")),
        sa.UniqueConstraint("jti_hash", name=op.f("uq_admin_refresh_sessions_jti_hash")),
    )
    op.create_index(
        "ix_admin_refresh_sessions_expires_at",
        "admin_refresh_sessions",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_admin_refresh_sessions_parent",
        "admin_refresh_sessions",
        ["parent_session_id"],
        unique=False,
    )
    op.create_index(
        "ix_admin_refresh_sessions_replaced_by",
        "admin_refresh_sessions",
        ["replaced_by_session_id"],
        unique=False,
    )
    op.create_index(
        "ix_admin_refresh_sessions_user_id",
        "admin_refresh_sessions",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_admin_refresh_sessions_user_id", table_name="admin_refresh_sessions")
    op.drop_index("ix_admin_refresh_sessions_replaced_by", table_name="admin_refresh_sessions")
    op.drop_index("ix_admin_refresh_sessions_parent", table_name="admin_refresh_sessions")
    op.drop_index("ix_admin_refresh_sessions_expires_at", table_name="admin_refresh_sessions")
    op.drop_table("admin_refresh_sessions")
