"""Token usage log: high-volume table, partitioned by ``created_at`` (RANGE).

PostgreSQL requires the partition key to be part of every UNIQUE / PRIMARY KEY,
so the PK is the composite ``(id, created_at)``.  ``id`` alone is still
unique per row thanks to ``BIGSERIAL`` semantics.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, desc, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TokenUsageLog(Base):
    __tablename__ = "token_usage_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        primary_key=True,
        nullable=False,
        server_default=func.now(),
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    service_type: Mapped[str] = mapped_column(String(100), nullable=False)
    tokens_consumed: Mapped[int] = mapped_column(Integer, nullable=False)

    request_params: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    response_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    processing_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    composio_tool: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mcp_server: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        Index("ix_token_usage_logs_user_id", "user_id"),
        Index("ix_token_usage_logs_service", "service_type"),
        Index("ix_token_usage_logs_created", desc("created_at")),
        {"postgresql_partition_by": "RANGE (created_at)"},
    )

    def __repr__(self) -> str:
        return (
            f"<TokenUsageLog id={self.id} user_id={self.user_id} "
            f"service={self.service_type} tokens={self.tokens_consumed}>"
        )
