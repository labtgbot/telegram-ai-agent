"""Daily-bonus claim ledger.

Issue #22 introduces a retention loop: a user can claim a "daily bonus"
once per UTC date and the bonus amount grows on consecutive days
(``10 → 12 → 15 → 20``, capped at 20).  The active streak length is
the source of truth for the next reward, so we need a durable place
to look it up — Redis caches the hot read-path but is allowed to be
evicted, so we duplicate every claim into this table.

One row per ``(user_id, claim_date)`` makes a duplicate claim raise an
``IntegrityError`` at the database layer — which is how
:class:`~app.services.daily_bonus.DailyBonusService` enforces "one
bonus per UTC day" even under concurrent requests.  Streak day is
stored explicitly so reading the latest row of a user is enough to
decide the next amount without re-scanning the ledger.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DailyBonusClaim(Base):
    __tablename__ = "daily_bonus_claims"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    # UTC calendar date — the issue's "day change at midnight UTC" rule.
    claim_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Position in the streak ladder for this claim (1-indexed).  The
    # service consults the configured amounts list with
    # ``amounts[min(streak_day - 1, len(amounts) - 1)]`` to derive the
    # reward, so this column doubles as a forward-compatible "level".
    streak_day: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)

    # Pointer to the credit row in ``transactions``.  Optional only to
    # keep the schema flexible for back-fills; the service always sets
    # it on the live path.
    transaction_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("transactions.id"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "claim_date", name="uq_daily_bonus_user_date"
        ),
        Index("ix_daily_bonus_user_id", "user_id"),
        Index(
            "ix_daily_bonus_user_date_desc",
            "user_id",
            "claim_date",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<DailyBonusClaim id={self.id} user_id={self.user_id} "
            f"claim_date={self.claim_date} streak_day={self.streak_day} "
            f"amount={self.amount}>"
        )


__all__ = ["DailyBonusClaim"]
