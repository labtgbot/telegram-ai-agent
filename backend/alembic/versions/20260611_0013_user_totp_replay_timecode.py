"""user totp replay timecode

Revision ID: 0013_user_totp_replay_timecode
Revises: 0012_account_deletion_failure
Create Date: 2026-06-11

Store the latest accepted TOTP timestep for replay protection.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013_user_totp_replay_timecode"
down_revision: str | Sequence[str] | None = "0012_account_deletion_failure"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("last_totp_timecode", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "last_totp_timecode")
