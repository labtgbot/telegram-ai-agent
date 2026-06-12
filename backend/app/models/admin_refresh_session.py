"""Server-side admin refresh-token sessions."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AdminRefreshSession(Base):
    """Persisted refresh-token state used to enforce rotation and logout."""

    __tablename__ = "admin_refresh_sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    jti_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parent_session_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("admin_refresh_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    replaced_by_session_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("admin_refresh_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_admin_refresh_sessions_user_id", "user_id"),
        Index("ix_admin_refresh_sessions_expires_at", "expires_at"),
        Index("ix_admin_refresh_sessions_parent", "parent_session_id"),
        Index("ix_admin_refresh_sessions_replaced_by", "replaced_by_session_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<AdminRefreshSession id={self.id} user_id={self.user_id} "
            f"expires_at={self.expires_at}>"
        )
