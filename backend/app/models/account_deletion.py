"""GDPR Art. 17 account-deletion requests.

A row in this table is created when a user calls
``DELETE /api/v1/user/me``. The actual anonymisation runs asynchronously
(see :mod:`app.workers.account_deletion`) after a 30-day grace period so
the user can cancel — ``POST /api/v1/user/me/cancel-deletion``.

Transactions reference ``users.id`` with ``ondelete=RESTRICT`` for legal
accounting retention (6 years), therefore the worker anonymises PII
in-place rather than deleting the user row.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

DELETION_STATUS_PENDING = "pending"
DELETION_STATUS_CANCELLED = "cancelled"
DELETION_STATUS_COMPLETED = "completed"
DELETION_STATUS_FAILED = "failed"

DELETION_STATUSES = (
    DELETION_STATUS_PENDING,
    DELETION_STATUS_CANCELLED,
    DELETION_STATUS_COMPLETED,
    DELETION_STATUS_FAILED,
)


class AccountDeletionRequest(Base):
    """One row per ``DELETE /user/me`` invocation."""

    __tablename__ = "account_deletion_requests"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=DELETION_STATUS_PENDING
    )

    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    scheduled_for: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    requested_via: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','cancelled','completed','failed')",
            name="account_deletion_requests_status_allowed",
        ),
        Index(
            "ix_account_deletion_pending",
            "scheduled_for",
            postgresql_where="status = 'pending'",
        ),
        Index(
            "uq_account_deletion_active",
            "user_id",
            unique=True,
            postgresql_where="status = 'pending'",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<AccountDeletionRequest id={self.id} user_id={self.user_id} "
            f"status={self.status} scheduled_for={self.scheduled_for}>"
        )


__all__ = [
    "AccountDeletionRequest",
    "DELETION_STATUSES",
    "DELETION_STATUS_CANCELLED",
    "DELETION_STATUS_COMPLETED",
    "DELETION_STATUS_FAILED",
    "DELETION_STATUS_PENDING",
]
