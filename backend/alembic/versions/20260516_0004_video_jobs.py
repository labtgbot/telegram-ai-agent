"""video generation: persistent job tracking

Revision ID: 0004_video_jobs
Revises: 0003_payment_idempotency
Create Date: 2026-05-16

Phase 2 introduces async video generation: the Composio video toolkit
returns a ``provider_job_id`` immediately and a polling worker drives
the job to completion (or failure + refund).  This migration adds the
``video_jobs`` table that backs the lifecycle.

Indexes:

* ``ix_video_jobs_user_id`` — user dashboards / quota counts;
* ``ix_video_jobs_status`` — the worker's "what's still pending" sweep;
* ``ix_video_jobs_created`` — admin export sort;
* ``ix_video_jobs_provider_id`` (partial, ``WHERE provider_job_id IS NOT NULL``) —
  reverse-lookup for provider callbacks if they ever land.
* ``uq_video_jobs_request_id`` — idempotency on the API ``request_id``
  so a Mini-App retry can't double-charge.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_video_jobs"
down_revision: str | Sequence[str] | None = "0003_payment_idempotency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "video_jobs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("tariff", sa.String(length=32), nullable=False),
        sa.Column("duration_s", sa.Integer(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("style", sa.String(length=100), nullable=True),
        sa.Column("reference_image_url", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("tokens_cost", sa.Integer(), nullable=False),
        sa.Column("provider_job_id", sa.String(length=255), nullable=True),
        sa.Column("composio_tool", sa.String(length=255), nullable=True),
        sa.Column("mcp_server", sa.String(length=255), nullable=True),
        sa.Column("result_url", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("transaction_id", sa.BigInteger(), nullable=True),
        sa.Column("refund_transaction_id", sa.BigInteger(), nullable=True),
        sa.Column("usage_log_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
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
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_video_jobs_user", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["transactions.id"],
            name="fk_video_jobs_transaction",
        ),
        sa.ForeignKeyConstraint(
            ["refund_transaction_id"],
            ["transactions.id"],
            name="fk_video_jobs_refund_transaction",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_video_jobs"),
        sa.UniqueConstraint("request_id", name="uq_video_jobs_request_id"),
        sa.CheckConstraint(
            "status IN ('pending','queued','in_progress','succeeded','failed','refunded')",
            name="video_jobs_status_allowed",
        ),
        sa.CheckConstraint(
            "duration_s > 0",
            name="video_jobs_duration_positive",
        ),
        sa.CheckConstraint(
            "tokens_cost >= 0",
            name="video_jobs_tokens_cost_nonnegative",
        ),
    )
    op.create_index("ix_video_jobs_user_id", "video_jobs", ["user_id"], unique=False)
    op.create_index("ix_video_jobs_status", "video_jobs", ["status"], unique=False)
    op.create_index("ix_video_jobs_created", "video_jobs", ["created_at"], unique=False)
    op.create_index(
        "ix_video_jobs_provider_id",
        "video_jobs",
        ["provider_job_id"],
        unique=False,
        postgresql_where=sa.text("provider_job_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_video_jobs_provider_id", table_name="video_jobs")
    op.drop_index("ix_video_jobs_created", table_name="video_jobs")
    op.drop_index("ix_video_jobs_status", table_name="video_jobs")
    op.drop_index("ix_video_jobs_user_id", table_name="video_jobs")
    op.drop_table("video_jobs")
