"""Unit tests for ``app.services.data_export``.

The service is "shape-stable": every test pins the JSON layout that the
Mini App download flow consumes. We stub the session so the tests
don't require Postgres — the service's queries are routed through a
single ``session.execute`` hook plus ``session.scalar`` for the
referral counter.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.exc import OperationalError

from app.models.chat_history import ChatMessage, ChatThread
from app.models.daily_bonus_claim import DailyBonusClaim
from app.models.subscription import Subscription
from app.models.transaction import Transaction
from app.services.data_export import build_user_data_export


@dataclass
class _StubUser:
    id: int = 42
    telegram_id: int = 4242
    username: str = "alice"
    first_name: str = "Alice"
    last_name: str | None = "Smith"
    language_code: str = "en"
    referral_code: str = "REF-42"
    referred_by: int | None = None
    token_balance: int = 100
    total_tokens_purchased: int = 100
    total_tokens_spent: int = 0
    total_requests: int = 0
    is_premium: bool = False
    premium_expires_at: datetime | None = None
    role: str = "user"
    created_at: datetime = datetime(2026, 1, 1, tzinfo=UTC)
    last_active_at: datetime = datetime(2026, 5, 16, tzinfo=UTC)
    last_login_at: datetime | None = None


class _ScalarsResult:
    """Mimic the parts of SQLAlchemy's ``Result`` that the service uses."""

    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def scalars(self):
        return self

    def all(self):
        return list(self._items)


class _FakeSession:
    """Routes select(...) to a per-model list and tracks scalar calls."""

    def __init__(self, *, queries: dict[type, list[Any]], referrals: int = 0) -> None:
        self._queries = queries
        self._referrals = referrals
        self.execute_calls: list[Any] = []
        self.execute_should_raise: type[Exception] | None = None

    async def execute(self, stmt):  # noqa: ANN001 — duck-typed
        self.execute_calls.append(stmt)
        if self.execute_should_raise is not None:
            raise self.execute_should_raise("boom", None, None)
        # ``stmt.column_descriptions[0]['type']`` is the queried model class.
        try:
            model = stmt.column_descriptions[0]["type"]
        except (AttributeError, IndexError, KeyError):
            return _ScalarsResult([])
        return _ScalarsResult(self._queries.get(model, []))

    async def scalar(self, stmt):  # noqa: ANN001 — duck-typed
        return self._referrals


@pytest.mark.asyncio
async def test_export_returns_stable_schema() -> None:
    user = _StubUser()
    session = _FakeSession(
        queries={
            Transaction: [
                Transaction(
                    id=1,
                    user_id=user.id,
                    transaction_type="purchase",
                    tokens_amount=100,
                    stars_amount=10,
                    usd_amount=Decimal("0.10"),
                    payment_status="completed",
                    created_at=datetime(2026, 5, 1, tzinfo=UTC),
                )
            ],
            Subscription: [],
            ChatThread: [],
            ChatMessage: [],
            DailyBonusClaim: [],
        },
        referrals=3,
    )

    export = await build_user_data_export(session, user=user)  # type: ignore[arg-type]
    payload = export.to_json()

    assert payload["schema_version"] == "1.0"
    assert payload["user"]["id"] == 42
    assert payload["user"]["telegram_id"] == 4242
    assert payload["transactions"][0]["transaction_type"] == "purchase"
    assert payload["transactions"][0]["tokens_amount"] == 100
    assert payload["transactions"][0]["usd_amount"] == "0.10"
    assert payload["referrals_summary"] == {"count": 3}
    # ``notes`` is empty on the happy path so consumers can rely on it.
    assert payload["notes"] == []


@pytest.mark.asyncio
async def test_chat_messages_are_truncated_and_annotated() -> None:
    user = _StubUser()
    big_chat = [
        ChatMessage(
            id=i,
            thread_id=1,
            user_id=user.id,
            role="user",
            content=f"msg {i}",
            tokens_consumed=0,
            metadata_json=None,
            created_at=datetime(2026, 5, 1, tzinfo=UTC),
        )
        for i in range(1, 7)
    ]
    session = _FakeSession(
        queries={
            Transaction: [],
            Subscription: [],
            ChatThread: [],
            ChatMessage: big_chat,
            DailyBonusClaim: [],
        }
    )

    export = await build_user_data_export(
        session, user=user, max_chat_messages=4  # type: ignore[arg-type]
    )

    assert len(export.chat_messages) == 4
    assert any("chat_messages: truncated" in note for note in export.notes)


@pytest.mark.asyncio
async def test_section_failure_degrades_gracefully() -> None:
    user = _StubUser()
    session = _FakeSession(
        queries={
            Transaction: [],
            Subscription: [],
            ChatThread: [],
            ChatMessage: [],
            DailyBonusClaim: [],
        }
    )
    session.execute_should_raise = OperationalError

    export = await build_user_data_export(session, user=user)  # type: ignore[arg-type]
    assert export.transactions == []
    # Every section is reported in notes when execute() raises.
    assert any("transactions: unavailable" in note for note in export.notes)
    assert any("subscriptions: unavailable" in note for note in export.notes)
