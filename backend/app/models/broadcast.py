"""Broadcast models (Phase 3, issue #28).

Captures the full lifecycle of a mass message: from draft → scheduled →
in-progress → completed (or cancelled), together with delivery stats per
recipient.

Two tables:

* ``broadcasts`` — one row per campaign.  Stores the rendered message
  payload (text, media, inline buttons), the audience selector and the
  running counters (queued / sent / delivered / failed / clicked).
* ``broadcast_recipients`` — one row per (broadcast, user) pair created
  by the worker as it iterates the audience.  Tracks per-recipient
  status, the Telegram ``message_id`` once delivered, the most recent
  error description and any click count if the message carries buttons.

Rows in either table are never overwritten with stale data — counters
are bumped atomically by the worker after each Telegram send, so a
crash mid-broadcast leaves a consistent snapshot.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

BROADCAST_STATUS_DRAFT = "draft"
BROADCAST_STATUS_SCHEDULED = "scheduled"
BROADCAST_STATUS_IN_PROGRESS = "in_progress"
BROADCAST_STATUS_COMPLETED = "completed"
BROADCAST_STATUS_CANCELLED = "cancelled"
BROADCAST_STATUS_FAILED = "failed"

BROADCAST_STATUSES: tuple[str, ...] = (
    BROADCAST_STATUS_DRAFT,
    BROADCAST_STATUS_SCHEDULED,
    BROADCAST_STATUS_IN_PROGRESS,
    BROADCAST_STATUS_COMPLETED,
    BROADCAST_STATUS_CANCELLED,
    BROADCAST_STATUS_FAILED,
)

BROADCAST_AUDIENCE_ALL = "all"
BROADCAST_AUDIENCE_PREMIUM = "premium"
BROADCAST_AUDIENCE_FREE = "free"
BROADCAST_AUDIENCE_INACTIVE_7D = "inactive_7d"
BROADCAST_AUDIENCE_CUSTOM = "custom"

BROADCAST_AUDIENCES: tuple[str, ...] = (
    BROADCAST_AUDIENCE_ALL,
    BROADCAST_AUDIENCE_PREMIUM,
    BROADCAST_AUDIENCE_FREE,
    BROADCAST_AUDIENCE_INACTIVE_7D,
    BROADCAST_AUDIENCE_CUSTOM,
)

RECIPIENT_STATUS_PENDING = "pending"
RECIPIENT_STATUS_SENT = "sent"
RECIPIENT_STATUS_DELIVERED = "delivered"
RECIPIENT_STATUS_FAILED = "failed"
RECIPIENT_STATUS_SKIPPED = "skipped"

RECIPIENT_STATUSES: tuple[str, ...] = (
    RECIPIENT_STATUS_PENDING,
    RECIPIENT_STATUS_SENT,
    RECIPIENT_STATUS_DELIVERED,
    RECIPIENT_STATUS_FAILED,
    RECIPIENT_STATUS_SKIPPED,
)


class Broadcast(Base):
    __tablename__ = "broadcasts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_by: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    parse_mode: Mapped[str | None] = mapped_column(String(16), nullable=True, server_default="HTML")
    media_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    media_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    buttons: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)

    audience: Mapped[str] = mapped_column(String(32), nullable=False)
    audience_filter: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=BROADCAST_STATUS_DRAFT
    )

    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    total_recipients: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    sent_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    delivered_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    clicks_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index("ix_broadcasts_status", "status"),
        Index("ix_broadcasts_scheduled_at", "scheduled_at"),
        Index("ix_broadcasts_created_by", "created_by"),
        Index("ix_broadcasts_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<Broadcast id={self.id} status={self.status} "
            f"audience={self.audience} total={self.total_recipients}>"
        )


class BroadcastRecipient(Base):
    __tablename__ = "broadcast_recipients"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    broadcast_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("broadcasts.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=RECIPIENT_STATUS_PENDING
    )
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    clicks: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("broadcast_id", "user_id", name="uq_broadcast_recipients_broadcast_id"),
        Index("ix_broadcast_recipients_broadcast_id", "broadcast_id"),
        Index("ix_broadcast_recipients_status", "status"),
        Index("ix_broadcast_recipients_user_id", "user_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<BroadcastRecipient id={self.id} broadcast_id={self.broadcast_id} "
            f"user_id={self.user_id} status={self.status}>"
        )
