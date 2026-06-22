"""add admin_settings.updated_by foreign key

Revision ID: 0016_admin_setting_fk
Revises: 0015_admin_refresh_sessions
Create Date: 2026-06-22
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0016_admin_setting_fk"
down_revision: str | Sequence[str] | None = "0015_admin_refresh_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE admin_settings
        SET updated_by = NULL
        WHERE updated_by IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM users
              WHERE users.id = admin_settings.updated_by
          )
        """
    )
    op.create_foreign_key(
        "fk_admin_settings_updated_by",
        "admin_settings",
        "users",
        ["updated_by"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_admin_settings_updated_by",
        "admin_settings",
        type_="foreignkey",
    )
