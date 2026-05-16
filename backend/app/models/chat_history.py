"""Chat history persistence for premium text-generation users.

Free-tier conversations live in Redis with a sliding TTL (see
:class:`app.services.text_generation.RedisConversationHistory`).  Premium
users get durable history backed by these two tables:

* ``chat_threads`` — one row per conversation; tracks the owning user,
  the active mode, the optional system prompt and the most recent turn
  timestamp so dashboards can sort by activity.
* ``chat_messages`` — append-only log of every turn.  ``role`` follows
  the OpenAI / Anthropic vocabulary plus a ``summary`` role used by the
  auto-summariser.

The schema mirrors what :class:`ChatTurn` already carries in memory so
read/write paths stay symmetric across Redis and DB back-ends.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# Allowed message roles.  Kept in sync with
# :data:`app.services.text_generation.KNOWN_ROLES`; duplicated here so the
# check constraint can be expressed without importing the service layer
# (alembic env imports models, not services).
CHAT_MESSAGE_ROLES = ("system", "user", "assistant", "summary")


class ChatThread(Base):
    __tablename__ = "chat_threads"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Caller-controlled identifier (UUID / short slug).  The application
    # uses it as the addressable thread key in URLs and bot callbacks, so
    # we store it alongside the surrogate ``id`` to keep both shapes
    # available without a join.
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)

    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mode: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="basic"
    )
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)

    message_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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
        Index("ix_chat_threads_user_id", "user_id"),
        Index("ix_chat_threads_user_external", "user_id", "external_id", unique=True),
        Index("ix_chat_threads_last_message", "last_message_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<ChatThread id={self.id} user_id={self.user_id} "
            f"external_id={self.external_id} mode={self.mode}>"
        )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    thread_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("chat_threads.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    tokens_consumed: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    composio_tool: Mapped[str | None] = mapped_column(String(255), nullable=True)
    transaction_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("transactions.id"), nullable=True
    )
    usage_log_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Free-form payload for tool calls / citations.  Kept JSONB so the
    # auto-summariser can collapse rich turns without losing structure.
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('system','user','assistant','summary')",
            name="chat_messages_role_allowed",
        ),
        Index("ix_chat_messages_thread_id_created", "thread_id", "created_at"),
        Index("ix_chat_messages_user_id", "user_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<ChatMessage id={self.id} thread_id={self.thread_id} "
            f"role={self.role}>"
        )


__all__ = ["CHAT_MESSAGE_ROLES", "ChatMessage", "ChatThread"]
