"""User model.

The ``token_balance >= 0`` invariant is enforced in code (services),
not via a CHECK constraint — see DATABASE_SCHEMA.md > Invariants.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    language_code: Mapped[str | None] = mapped_column(
        String(10), nullable=True, server_default="ru"
    )

    token_balance: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    total_tokens_purchased: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    total_tokens_spent: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )

    is_premium: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    premium_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    total_requests: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )

    referred_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=True
    )
    referral_code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)

    is_banned: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    ban_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    banned_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    role: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="user"
    )
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    last_totp_timecode: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index(
            "ix_users_premium",
            "is_premium",
            postgresql_where="is_premium = TRUE",
        ),
        Index(
            "ix_users_role",
            "role",
            postgresql_where="role <> 'user'",
        ),
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} telegram_id={self.telegram_id}>"
