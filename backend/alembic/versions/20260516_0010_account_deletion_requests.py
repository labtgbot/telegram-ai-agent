"""account deletion requests for GDPR Art. 17

Revision ID: 0010_account_deletion
Revises: 0009_admin_content
Create Date: 2026-05-16

Issue #35 adds a soft-delete grace period for ``DELETE /api/v1/user/me``.
A row is created when the user requests deletion and processed by the
:mod:`app.workers.account_deletion` worker after 30 days. Users may
cancel within that window via ``POST /user/me/cancel-deletion``.

A partial unique index guarantees a user can have at most one *active*
(pending) request, while keeping historic rows for audit.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010_account_deletion"
down_revision: str | Sequence[str] | None = "0009_admin_content"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "account_deletion_requests",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_via", sa.String(length=32), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_account_deletion_requests_user_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_account_deletion_requests"),
        sa.CheckConstraint(
            "status IN ('pending','cancelled','completed','failed')",
            name="account_deletion_requests_status_allowed",
        ),
    )
    op.create_index(
        "ix_account_deletion_pending",
        "account_deletion_requests",
        ["scheduled_for"],
        unique=False,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "uq_account_deletion_active",
        "account_deletion_requests",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_account_deletion_active", table_name="account_deletion_requests"
    )
    op.drop_index(
        "ix_account_deletion_pending", table_name="account_deletion_requests"
    )
    op.drop_table("account_deletion_requests")
