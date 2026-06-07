"""account deletion failure reason

Revision ID: 0012_account_deletion_failure
Revises: 0011_token_usage_partitions
Create Date: 2026-06-07

Persist the worker-side failure timestamp and reason separately from the
user-supplied deletion ``reason``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012_account_deletion_failure"
down_revision: str | Sequence[str] | None = "0011_token_usage_partitions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "account_deletion_requests",
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "account_deletion_requests",
        sa.Column("failure_reason", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("account_deletion_requests", "failure_reason")
    op.drop_column("account_deletion_requests", "failed_at")
