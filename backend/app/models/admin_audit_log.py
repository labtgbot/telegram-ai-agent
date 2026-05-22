"""Admin audit log: durable record of every privileged action.

Every mutation performed by an admin against a user (or system entity)
should write one row here.  Rows are never updated or deleted; the table
is the source of truth for compliance and customer-support reviews.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    admin_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    target_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_admin_audit_admin", "admin_id"),
        Index("ix_admin_audit_target", "target_user_id"),
        Index("ix_admin_audit_action", "action"),
        Index("ix_admin_audit_created", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<AdminAuditLog id={self.id} admin_id={self.admin_id} "
            f"action={self.action} target={self.target_user_id}>"
        )
