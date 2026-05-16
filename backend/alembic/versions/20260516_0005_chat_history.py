"""text generation: persistent chat history for premium users

Revision ID: 0005_chat_history
Revises: 0004_video_jobs
Create Date: 2026-05-16

Phase 2 (issue #15) introduces three text-generation modes —
``basic`` / ``advanced`` / ``autonomous_agent`` — and a multi-turn
conversation surface.  Free users keep their history in Redis with a
sliding TTL; premium users get durable history backed by these tables.

Tables
------
* ``chat_threads`` — one row per conversation, owned by a user, keyed by
  a caller-controlled ``external_id`` (UUID / slug) so URLs stay stable
  across resumes.
* ``chat_messages`` — append-only log of every turn (role + content +
  optional tool/transaction linkage).

Indexes
-------
* ``ix_chat_threads_user_id`` — list-threads-for-user queries;
* ``ix_chat_threads_user_external`` (UNIQUE) — fast lookup by
  ``(user_id, external_id)`` and idempotency when a client retries the
  thread create;
* ``ix_chat_threads_last_message`` — admin dashboards / "recent
  conversations" sort;
* ``ix_chat_messages_thread_id_created`` — primary access path
  (rendering a thread in chronological order);
* ``ix_chat_messages_user_id`` — moderation / per-user export.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_chat_history"
down_revision: str | Sequence[str] | None = "0004_video_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_threads",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column(
            "mode",
            sa.String(length=32),
            nullable=False,
            server_default="basic",
        ),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column(
            "message_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "last_message_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_chat_threads_user", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chat_threads"),
    )
    op.create_index(
        "ix_chat_threads_user_id", "chat_threads", ["user_id"], unique=False
    )
    op.create_index(
        "ix_chat_threads_user_external",
        "chat_threads",
        ["user_id", "external_id"],
        unique=True,
    )
    op.create_index(
        "ix_chat_threads_last_message",
        "chat_threads",
        ["last_message_at"],
        unique=False,
    )

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("thread_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "tokens_consumed",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("composio_tool", sa.String(length=255), nullable=True),
        sa.Column("transaction_id", sa.BigInteger(), nullable=True),
        sa.Column("usage_log_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "metadata_json",
            sa.dialects.postgresql.JSONB(),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["thread_id"],
            ["chat_threads.id"],
            name="fk_chat_messages_thread",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_chat_messages_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["transactions.id"],
            name="fk_chat_messages_transaction",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chat_messages"),
        sa.CheckConstraint(
            "role IN ('system','user','assistant','summary')",
            name="chat_messages_role_allowed",
        ),
    )
    op.create_index(
        "ix_chat_messages_thread_id_created",
        "chat_messages",
        ["thread_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_chat_messages_user_id",
        "chat_messages",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_chat_messages_user_id", table_name="chat_messages")
    op.drop_index(
        "ix_chat_messages_thread_id_created", table_name="chat_messages"
    )
    op.drop_table("chat_messages")
    op.drop_index("ix_chat_threads_last_message", table_name="chat_threads")
    op.drop_index("ix_chat_threads_user_external", table_name="chat_threads")
    op.drop_index("ix_chat_threads_user_id", table_name="chat_threads")
    op.drop_table("chat_threads")
