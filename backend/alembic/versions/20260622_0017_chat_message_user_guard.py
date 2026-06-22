"""add chat message thread owner guard

Revision ID: 0017_chat_message_user_guard
Revises: 0016_admin_setting_fk
Create Date: 2026-06-22
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0017_chat_message_user_guard"
down_revision: str | Sequence[str] | None = "0016_admin_setting_fk"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE chat_messages
        SET user_id = chat_threads.user_id
        FROM chat_threads
        WHERE chat_messages.thread_id = chat_threads.id
          AND chat_messages.user_id <> chat_threads.user_id
        """
    )
    op.create_unique_constraint(
        "uq_chat_threads_id_user_id",
        "chat_threads",
        ["id", "user_id"],
    )
    op.create_foreign_key(
        "fk_chat_messages_thread_user",
        "chat_messages",
        "chat_threads",
        ["thread_id", "user_id"],
        ["id", "user_id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_chat_messages_thread_user",
        "chat_messages",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_chat_threads_id_user_id",
        "chat_threads",
        type_="unique",
    )
