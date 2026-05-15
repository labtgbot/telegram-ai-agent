"""auth: add role, totp and last_login fields to users

Revision ID: 0002_auth_user_columns
Revises: 0001_baseline
Create Date: 2026-05-16

Adds the columns required by Phase 1 Authentication & Authorization:

* ``role`` — RBAC role (``user`` / ``support_admin`` / ``analyst`` /
  ``super_admin`` / ``banned``); default ``user`` for existing rows.
* ``totp_secret`` / ``totp_enabled`` — TOTP (RFC 6238) state for admins.
* ``last_login_at`` — timestamp of the last successful admin login.

A partial index ``ix_users_role`` accelerates admin lookups while
keeping the index tiny for the dominant ``user`` role.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_auth_user_columns"
down_revision: str | Sequence[str] | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "role",
            sa.String(length=32),
            nullable=False,
            server_default="user",
        ),
    )
    op.add_column(
        "users",
        sa.Column("totp_secret", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "totp_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "users",
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_users_role",
        "users",
        ["role"],
        unique=False,
        postgresql_where=sa.text("role <> 'user'"),
    )


def downgrade() -> None:
    op.drop_index("ix_users_role", table_name="users")
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "totp_enabled")
    op.drop_column("users", "totp_secret")
    op.drop_column("users", "role")
