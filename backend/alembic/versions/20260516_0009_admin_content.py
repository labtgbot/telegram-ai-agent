"""admin content management: prompt templates, FAQ items, welcome messages

Revision ID: 0009_admin_content
Revises: 0008_broadcasts
Create Date: 2026-05-16

Issue #29 introduces the Content Management section of the admin CRM.
Three tables capture user-facing copy that admins can edit without a
redeploy:

* ``prompt_templates`` — named prompts the bot can suggest to users.
* ``faq_items`` — Q/A pairs surfaced through ``/help``.
* ``welcome_messages`` — onboarding copy sent to new users per locale.

System-level toggles (maintenance mode, composio tool catalog) reuse
the existing ``admin_settings`` key/value store, so no extra tables are
needed for those.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009_admin_content"
down_revision: str | Sequence[str] | None = "0008_broadcasts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "prompt_templates",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("locale", sa.String(length=8), nullable=False, server_default="en"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
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
            ["created_by"],
            ["users.id"],
            name="fk_prompt_templates_created_by",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name="fk_prompt_templates_updated_by",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_prompt_templates"),
        sa.UniqueConstraint("code", name="uq_prompt_templates_code"),
    )
    op.create_index(
        "ix_prompt_templates_category", "prompt_templates", ["category"], unique=False
    )
    op.create_index(
        "ix_prompt_templates_is_active", "prompt_templates", ["is_active"], unique=False
    )
    op.create_index(
        "ix_prompt_templates_locale", "prompt_templates", ["locale"], unique=False
    )

    op.create_table(
        "faq_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("question", sa.String(length=512), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("locale", sa.String(length=8), nullable=False, server_default="en"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
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
            ["created_by"],
            ["users.id"],
            name="fk_faq_items_created_by",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name="fk_faq_items_updated_by",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_faq_items"),
    )
    op.create_index("ix_faq_items_category", "faq_items", ["category"], unique=False)
    op.create_index("ix_faq_items_is_active", "faq_items", ["is_active"], unique=False)
    op.create_index("ix_faq_items_locale", "faq_items", ["locale"], unique=False)
    op.create_index("ix_faq_items_sort_order", "faq_items", ["sort_order"], unique=False)

    op.create_table(
        "welcome_messages",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("locale", sa.String(length=8), nullable=False, server_default="en"),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
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
            ["created_by"],
            ["users.id"],
            name="fk_welcome_messages_created_by",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name="fk_welcome_messages_updated_by",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_welcome_messages"),
    )
    op.create_index(
        "ix_welcome_messages_locale", "welcome_messages", ["locale"], unique=False
    )
    op.create_index(
        "ix_welcome_messages_is_active", "welcome_messages", ["is_active"], unique=False
    )
    # At most one active welcome per locale — DB-level invariant.
    op.create_index(
        "uq_welcome_messages_active_per_locale",
        "welcome_messages",
        ["locale"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_welcome_messages_active_per_locale", table_name="welcome_messages"
    )
    op.drop_index("ix_welcome_messages_is_active", table_name="welcome_messages")
    op.drop_index("ix_welcome_messages_locale", table_name="welcome_messages")
    op.drop_table("welcome_messages")

    op.drop_index("ix_faq_items_sort_order", table_name="faq_items")
    op.drop_index("ix_faq_items_locale", table_name="faq_items")
    op.drop_index("ix_faq_items_is_active", table_name="faq_items")
    op.drop_index("ix_faq_items_category", table_name="faq_items")
    op.drop_table("faq_items")

    op.drop_index("ix_prompt_templates_locale", table_name="prompt_templates")
    op.drop_index("ix_prompt_templates_is_active", table_name="prompt_templates")
    op.drop_index("ix_prompt_templates_category", table_name="prompt_templates")
    op.drop_table("prompt_templates")
