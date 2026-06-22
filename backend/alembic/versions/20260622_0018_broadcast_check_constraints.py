"""add broadcast value check constraints

Revision ID: 0018_broadcast_check_constraints
Revises: 0017_chat_message_user_guard
Create Date: 2026-06-22
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0018_broadcast_check_constraints"
down_revision: str | Sequence[str] | None = "0017_chat_message_user_guard"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        "broadcasts_status_allowed",
        "broadcasts",
        "status IN ('draft','scheduled','in_progress','completed','cancelled','failed')",
    )
    op.create_check_constraint(
        "broadcasts_audience_allowed",
        "broadcasts",
        "audience IN ('all','premium','free','inactive_7d','custom')",
    )
    op.create_check_constraint(
        "broadcast_recipients_status_allowed",
        "broadcast_recipients",
        "status IN ('pending','sent','delivered','failed','skipped')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "broadcast_recipients_status_allowed",
        "broadcast_recipients",
        type_="check",
    )
    op.drop_constraint(
        "broadcasts_audience_allowed",
        "broadcasts",
        type_="check",
    )
    op.drop_constraint(
        "broadcasts_status_allowed",
        "broadcasts",
        type_="check",
    )
