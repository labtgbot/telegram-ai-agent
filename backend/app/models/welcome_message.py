"""Welcome messages shown to new users (Phase 3, issue #29).

Admins author one or more welcome messages per ``locale``.  Only one row
per locale may be ``is_active = true`` at a time — the service layer
enforces that invariant when activating a row.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class WelcomeMessage(Base):
    __tablename__ = "welcome_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    locale: Mapped[str] = mapped_column(String(8), nullable=False, server_default="en")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    created_by: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_by: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

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
        Index("ix_welcome_messages_locale", "locale"),
        Index("ix_welcome_messages_is_active", "is_active"),
    )

    def __repr__(self) -> str:
        return (
            f"<WelcomeMessage id={self.id} locale={self.locale} "
            f"active={self.is_active}>"
        )
