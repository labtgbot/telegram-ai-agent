"""drop redundant user lookup indexes

Revision ID: 0014_drop_redundant_user_indexes
Revises: 0013_user_totp_replay_timecode
Create Date: 2026-06-11

Remove duplicate non-unique indexes covered by unique constraints.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0014_drop_redundant_user_indexes"
down_revision: str | Sequence[str] | None = "0013_user_totp_replay_timecode"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_users_telegram_id", table_name="users")
    op.drop_index("ix_users_referral", table_name="users")


def downgrade() -> None:
    op.create_index("ix_users_referral", "users", ["referral_code"], unique=False)
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"], unique=False)
