"""Video generation job: long-running, polled until the provider completes.

Unlike images (synchronous), video generation is asynchronous: the
provider returns a ``provider_job_id`` immediately and we poll status
until ``succeeded``/``failed``.  This row is the single source of truth
for the whole lifecycle — it records what the user asked for, what we
charged, the foreign provider job id, the final URL, and which audit
rows (``transactions``, ``token_usage_logs``) belong to the call.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# Lifecycle states.  ``pending`` is the row's initial state right after
# row creation but before the first provider call; ``queued`` means the
# provider has accepted the job; ``in_progress`` is set on the first
# in-progress poll response; terminal states are ``succeeded`` /
# ``failed`` / ``refunded`` (refund applied after a confirmed failure).
VIDEO_JOB_STATUSES = (
    "pending",
    "queued",
    "in_progress",
    "succeeded",
    "failed",
    "refunded",
)

VIDEO_JOB_TERMINAL_STATUSES = frozenset({"succeeded", "failed", "refunded"})


class VideoJob(Base):
    __tablename__ = "video_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    request_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    tariff: Mapped[str] = mapped_column(String(32), nullable=False)
    duration_s: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    style: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reference_image_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="pending"
    )
    tokens_cost: Mapped[int] = mapped_column(Integer, nullable=False)

    provider_job_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    composio_tool: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mcp_server: Mapped[str | None] = mapped_column(String(255), nullable=True)

    result_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    transaction_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("transactions.id"), nullable=True
    )
    refund_transaction_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("transactions.id"), nullable=True
    )
    usage_log_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','queued','in_progress','succeeded','failed','refunded')",
            name="video_jobs_status_allowed",
        ),
        CheckConstraint(
            "duration_s > 0",
            name="video_jobs_duration_positive",
        ),
        CheckConstraint(
            "tokens_cost >= 0",
            name="video_jobs_tokens_cost_nonnegative",
        ),
        Index("ix_video_jobs_user_id", "user_id"),
        Index("ix_video_jobs_status", "status"),
        Index("ix_video_jobs_created", "created_at"),
        Index(
            "ix_video_jobs_provider_id",
            "provider_job_id",
            postgresql_where="provider_job_id IS NOT NULL",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<VideoJob id={self.id} user_id={self.user_id} "
            f"tariff={self.tariff} status={self.status}>"
        )
