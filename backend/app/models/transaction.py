"""Transaction model: every token movement is recorded here."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

TRANSACTION_TYPES = ("purchase", "spend", "bonus", "refund", "manual_bonus")


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    transaction_type: Mapped[str] = mapped_column(String(50), nullable=False)

    tokens_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    stars_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    usd_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)

    package_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    discount_percent: Mapped[int | None] = mapped_column(
        Integer, nullable=True, server_default="0"
    )

    payment_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payment_status: Mapped[str | None] = mapped_column(
        String(50), nullable=True, server_default="pending"
    )
    payment_method: Mapped[str | None] = mapped_column(String(50), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "transaction_type IN ('purchase','spend','bonus','refund','manual_bonus')",
            name="transaction_type_allowed",
        ),
        Index("ix_transactions_user_id", "user_id"),
        Index("ix_transactions_type", "transaction_type"),
        Index("ix_transactions_created", "created_at", postgresql_using="btree"),
    )

    def __repr__(self) -> str:
        return (
            f"<Transaction id={self.id} user_id={self.user_id} "
            f"type={self.transaction_type} tokens={self.tokens_amount}>"
        )
