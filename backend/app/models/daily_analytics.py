"""Pre-aggregated daily metrics, one row per day."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Integer, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DailyAnalytics(Base):
    __tablename__ = "daily_analytics"

    date: Mapped[date] = mapped_column(Date, primary_key=True)

    total_users: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    new_users: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    active_users: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    premium_users: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    total_tokens_sold: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    total_stars_revenue: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    total_usd_revenue: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, server_default="0"
    )

    total_requests: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    image_generations: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    video_generations: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    text_queries: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    avg_tokens_per_user: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    conversion_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<DailyAnalytics date={self.date}>"
