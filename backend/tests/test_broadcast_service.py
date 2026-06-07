"""Database-backed integration tests for the broadcast service (issue #28).

Covers the SQL building blocks behind the Broadcast CRM section:
audience filters, audience preview, create + audit, cancel + cascade,
list / get / stats, due-broadcast picker, and the drain loop with a
fake Telegram client (including the 429 retry-after path).

Tests skip automatically when no PostgreSQL is available (see
``conftest.py``).
"""
from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select

from app.models.admin_audit_log import AdminAuditLog
from app.models.broadcast import (
    BROADCAST_AUDIENCE_ALL,
    BROADCAST_AUDIENCE_CUSTOM,
    BROADCAST_AUDIENCE_FREE,
    BROADCAST_AUDIENCE_INACTIVE_7D,
    BROADCAST_AUDIENCE_PREMIUM,
    BROADCAST_STATUS_CANCELLED,
    BROADCAST_STATUS_COMPLETED,
    BROADCAST_STATUS_DRAFT,
    BROADCAST_STATUS_IN_PROGRESS,
    BROADCAST_STATUS_SCHEDULED,
    RECIPIENT_STATUS_DELIVERED,
    RECIPIENT_STATUS_FAILED,
    RECIPIENT_STATUS_PENDING,
    RECIPIENT_STATUS_SKIPPED,
    Broadcast,
    BroadcastRecipient,
)
from app.models.user import User
from app.services.broadcast import (
    BROADCAST_AUDIT_CANCEL,
    BROADCAST_AUDIT_CREATE,
    BROADCAST_AUDIT_FINISH,
    BROADCAST_DRAIN_STALE_AFTER,
    BroadcastButton,
    BroadcastDraft,
    BroadcastNotCancellableError,
    BroadcastNotFoundError,
    EmptyAudienceError,
    InvalidAudienceError,
    InvalidBroadcastPayloadError,
    TelegramSendResult,
    _retry_after_from_description,
    build_audience_query,
    build_reply_markup,
    cancel_broadcast,
    create_broadcast,
    drain_broadcast,
    fetch_pending_recipients,
    get_broadcast,
    get_broadcast_stats,
    list_broadcasts,
    list_due_broadcasts,
    preview_audience,
    record_click,
    record_recipient_result,
    send_one,
)

# ---------------------------------------------------------------- helpers

_NEXT_TID = 7_100_000


def _next_telegram_id() -> int:
    global _NEXT_TID
    _NEXT_TID += 1
    return _NEXT_TID


async def _make_user(
    session,
    *,
    username: str | None = None,
    role: str = "user",
    is_premium: bool = False,
    is_banned: bool = False,
    last_active_at: datetime | None = None,
) -> User:
    tid = _next_telegram_id()
    user = User(
        telegram_id=tid,
        username=username or f"u{tid}",
        first_name="First",
        referral_code=f"BC-{tid}",
        role=role,
        is_premium=is_premium,
        is_banned=is_banned,
    )
    if last_active_at is not None:
        user.last_active_at = last_active_at
    session.add(user)
    await session.flush()
    return user


def _draft(
    *,
    text: str = "Hi there!",
    audience: str = BROADCAST_AUDIENCE_ALL,
    audience_filter: dict[str, Any] | None = None,
    title: str | None = None,
    parse_mode: str | None = "HTML",
    media_type: str | None = None,
    media_url: str | None = None,
    buttons: tuple[BroadcastButton, ...] = (),
    scheduled_at: datetime | None = None,
) -> BroadcastDraft:
    return BroadcastDraft(
        text=text,
        title=title,
        parse_mode=parse_mode,
        media_type=media_type,
        media_url=media_url,
        buttons=buttons,
        audience=audience,
        audience_filter=audience_filter,
        scheduled_at=scheduled_at,
    )


# ---------------------------------------------------------------- audience query


@pytest.mark.asyncio
async def test_build_audience_query_all_excludes_banned(db_session) -> None:
    alive = await _make_user(db_session, username="alive1")
    banned = await _make_user(db_session, username="banned1", is_banned=True)

    stmt = build_audience_query(BROADCAST_AUDIENCE_ALL)
    ids = {u.id for u in (await db_session.execute(stmt)).scalars().all()}
    assert alive.id in ids
    assert banned.id not in ids


@pytest.mark.asyncio
async def test_build_audience_query_premium_vs_free(db_session) -> None:
    free = await _make_user(db_session, username="freeguy", is_premium=False)
    paid = await _make_user(db_session, username="paidguy", is_premium=True)

    premium = await db_session.execute(build_audience_query(BROADCAST_AUDIENCE_PREMIUM))
    free_q = await db_session.execute(build_audience_query(BROADCAST_AUDIENCE_FREE))

    premium_ids = {u.id for u in premium.scalars().all()}
    free_ids = {u.id for u in free_q.scalars().all()}

    assert paid.id in premium_ids
    assert free.id not in premium_ids
    assert free.id in free_ids
    assert paid.id not in free_ids


@pytest.mark.asyncio
async def test_build_audience_query_inactive_7d(db_session) -> None:
    now = datetime(2026, 5, 16, tzinfo=UTC)
    fresh = await _make_user(
        db_session, username="fresh", last_active_at=now - timedelta(days=1)
    )
    stale = await _make_user(
        db_session, username="stale", last_active_at=now - timedelta(days=30)
    )

    stmt = build_audience_query(BROADCAST_AUDIENCE_INACTIVE_7D, now=now)
    rows = (await db_session.execute(stmt)).scalars().all()
    ids = {u.id for u in rows}
    assert stale.id in ids
    assert fresh.id not in ids


@pytest.mark.asyncio
async def test_build_audience_query_custom_telegram_ids(db_session) -> None:
    a = await _make_user(db_session, username="customA")
    b = await _make_user(db_session, username="customB")
    other = await _make_user(db_session, username="other")

    stmt = build_audience_query(
        BROADCAST_AUDIENCE_CUSTOM,
        audience_filter={"telegram_ids": [a.telegram_id, b.telegram_id]},
    )
    rows = (await db_session.execute(stmt)).scalars().all()
    ids = {u.id for u in rows}
    assert ids == {a.id, b.id}
    assert other.id not in ids


@pytest.mark.asyncio
async def test_build_audience_query_custom_requires_filter() -> None:
    with pytest.raises(InvalidAudienceError):
        build_audience_query(BROADCAST_AUDIENCE_CUSTOM)
    with pytest.raises(InvalidAudienceError):
        build_audience_query(BROADCAST_AUDIENCE_CUSTOM, audience_filter={})
    with pytest.raises(InvalidAudienceError):
        build_audience_query(
            BROADCAST_AUDIENCE_CUSTOM,
            audience_filter={"telegram_ids": ["not-a-number"]},
        )


@pytest.mark.asyncio
async def test_build_audience_query_unknown_audience() -> None:
    with pytest.raises(InvalidAudienceError):
        build_audience_query("rocket-launch")


# ---------------------------------------------------------------- preview_audience


@pytest.mark.asyncio
async def test_preview_audience_counts_match_query(db_session) -> None:
    await _make_user(db_session, username="prevA", is_premium=True)
    await _make_user(db_session, username="prevB", is_premium=True)
    await _make_user(db_session, username="prevC", is_premium=False)

    count_premium = await preview_audience(db_session, audience=BROADCAST_AUDIENCE_PREMIUM)
    assert count_premium >= 2


# ---------------------------------------------------------------- create_broadcast


@pytest.mark.asyncio
async def test_create_broadcast_persists_recipients_and_audit(db_session) -> None:
    admin = await _make_user(db_session, username="admin", role="support_admin")
    u1 = await _make_user(db_session, username="rcpt1")
    u2 = await _make_user(db_session, username="rcpt2")

    broadcast = await create_broadcast(
        db_session,
        admin=admin,
        draft=_draft(
            text="<b>Hello</b>",
            title="Spring sale",
            audience=BROADCAST_AUDIENCE_CUSTOM,
            audience_filter={"telegram_ids": [u1.telegram_id, u2.telegram_id]},
        ),
        ip_address="203.0.113.1",
        user_agent="tests/1.0",
    )

    assert broadcast.id is not None
    assert broadcast.created_by == admin.id
    assert broadcast.status == BROADCAST_STATUS_DRAFT
    assert broadcast.title == "Spring sale"
    assert broadcast.total_recipients == 2

    rows = (
        await db_session.execute(
            select(BroadcastRecipient).where(
                BroadcastRecipient.broadcast_id == broadcast.id
            )
        )
    ).scalars().all()
    assert {r.user_id for r in rows} == {u1.id, u2.id}
    assert all(r.status == RECIPIENT_STATUS_PENDING for r in rows)

    audit_row = (
        await db_session.execute(
            select(AdminAuditLog).where(
                AdminAuditLog.action == BROADCAST_AUDIT_CREATE,
                AdminAuditLog.admin_id == admin.id,
            )
        )
    ).scalars().first()
    assert audit_row is not None
    assert audit_row.payload["broadcast_id"] == broadcast.id
    assert audit_row.payload["audience"] == BROADCAST_AUDIENCE_CUSTOM
    assert audit_row.payload["total_recipients"] == 2
    assert audit_row.ip_address == "203.0.113.1"
    assert audit_row.user_agent == "tests/1.0"


@pytest.mark.asyncio
async def test_create_broadcast_schedules_when_future(db_session) -> None:
    admin = await _make_user(db_session, role="support_admin")
    await _make_user(db_session, username="someone")

    later = datetime.now(UTC) + timedelta(hours=2)
    broadcast = await create_broadcast(
        db_session,
        admin=admin,
        draft=_draft(audience=BROADCAST_AUDIENCE_ALL, scheduled_at=later),
    )
    assert broadcast.status == BROADCAST_STATUS_SCHEDULED
    assert broadcast.scheduled_at is not None


@pytest.mark.asyncio
async def test_create_broadcast_empty_audience_raises(db_session) -> None:
    admin = await _make_user(db_session, role="support_admin")
    bogus_id = 99_999_999_999

    with pytest.raises(EmptyAudienceError):
        await create_broadcast(
            db_session,
            admin=admin,
            draft=_draft(
                audience=BROADCAST_AUDIENCE_CUSTOM,
                audience_filter={"telegram_ids": [bogus_id]},
            ),
        )


@pytest.mark.asyncio
async def test_create_broadcast_validates_text_length(db_session) -> None:
    admin = await _make_user(db_session, role="support_admin")
    await _make_user(db_session)

    with pytest.raises(InvalidBroadcastPayloadError):
        await create_broadcast(db_session, admin=admin, draft=_draft(text=""))

    with pytest.raises(InvalidBroadcastPayloadError):
        await create_broadcast(db_session, admin=admin, draft=_draft(text="x" * 5000))


@pytest.mark.asyncio
async def test_create_broadcast_validates_media(db_session) -> None:
    admin = await _make_user(db_session, role="support_admin")
    await _make_user(db_session)

    # media_type set without media_url
    with pytest.raises(InvalidBroadcastPayloadError):
        await create_broadcast(
            db_session,
            admin=admin,
            draft=_draft(media_type="photo", media_url=None),
        )
    # unsupported media_type
    with pytest.raises(InvalidBroadcastPayloadError):
        await create_broadcast(
            db_session,
            admin=admin,
            draft=_draft(media_type="gif", media_url="https://x"),
        )


@pytest.mark.asyncio
async def test_create_broadcast_validates_button_payload(db_session) -> None:
    admin = await _make_user(db_session, role="support_admin")
    await _make_user(db_session)

    # button without url or callback_data
    with pytest.raises(InvalidBroadcastPayloadError):
        await create_broadcast(
            db_session,
            admin=admin,
            draft=_draft(buttons=(BroadcastButton(text="hi"),)),
        )

    # too many buttons
    too_many = tuple(
        BroadcastButton(text=f"b{i}", url=f"https://x/{i}") for i in range(10)
    )
    with pytest.raises(InvalidBroadcastPayloadError):
        await create_broadcast(db_session, admin=admin, draft=_draft(buttons=too_many))


# ---------------------------------------------------------------- cancel_broadcast


@pytest.mark.asyncio
async def test_cancel_broadcast_marks_cancelled_and_skips_pending(db_session) -> None:
    admin = await _make_user(db_session, role="support_admin")
    u = await _make_user(db_session)

    broadcast = await create_broadcast(
        db_session,
        admin=admin,
        draft=_draft(
            audience=BROADCAST_AUDIENCE_CUSTOM,
            audience_filter={"telegram_ids": [u.telegram_id]},
        ),
    )
    cancelled = await cancel_broadcast(
        db_session, admin=admin, broadcast_id=broadcast.id
    )
    assert cancelled.status == BROADCAST_STATUS_CANCELLED
    assert cancelled.cancelled_at is not None
    assert cancelled.finished_at is not None

    # all pending recipients are now skipped
    rows = (
        await db_session.execute(
            select(BroadcastRecipient).where(
                BroadcastRecipient.broadcast_id == broadcast.id
            )
        )
    ).scalars().all()
    assert all(r.status == RECIPIENT_STATUS_SKIPPED for r in rows)
    assert all(r.error == "cancelled_by_admin" for r in rows)

    # audit row written
    audit = (
        await db_session.execute(
            select(AdminAuditLog).where(AdminAuditLog.action == BROADCAST_AUDIT_CANCEL)
        )
    ).scalars().first()
    assert audit is not None
    assert audit.payload["broadcast_id"] == broadcast.id


@pytest.mark.asyncio
async def test_cancel_broadcast_rejects_completed(db_session) -> None:
    admin = await _make_user(db_session, role="support_admin")
    u = await _make_user(db_session)

    broadcast = await create_broadcast(
        db_session,
        admin=admin,
        draft=_draft(
            audience=BROADCAST_AUDIENCE_CUSTOM,
            audience_filter={"telegram_ids": [u.telegram_id]},
        ),
    )
    broadcast.status = BROADCAST_STATUS_COMPLETED
    await db_session.flush()

    with pytest.raises(BroadcastNotCancellableError):
        await cancel_broadcast(db_session, admin=admin, broadcast_id=broadcast.id)


@pytest.mark.asyncio
async def test_cancel_broadcast_missing_raises(db_session) -> None:
    admin = await _make_user(db_session, role="support_admin")
    with pytest.raises(BroadcastNotFoundError):
        await cancel_broadcast(db_session, admin=admin, broadcast_id=999_999_999)


# ---------------------------------------------------------------- list / get / stats


@pytest.mark.asyncio
async def test_list_broadcasts_filters_and_paginates(db_session) -> None:
    admin = await _make_user(db_session, role="support_admin")
    u = await _make_user(db_session)

    created: list[Broadcast] = []
    for i in range(3):
        b = await create_broadcast(
            db_session,
            admin=admin,
            draft=_draft(
                text=f"msg {i}",
                audience=BROADCAST_AUDIENCE_CUSTOM,
                audience_filter={"telegram_ids": [u.telegram_id]},
            ),
        )
        created.append(b)

    # Mark one completed
    created[0].status = BROADCAST_STATUS_COMPLETED
    await db_session.flush()

    page = await list_broadcasts(db_session, page=1, limit=2)
    assert page.total >= 3
    assert page.has_more is True
    assert len(page.items) == 2

    only_completed = await list_broadcasts(db_session, status=BROADCAST_STATUS_COMPLETED)
    assert all(item.status == BROADCAST_STATUS_COMPLETED for item in only_completed.items)
    assert created[0].id in {item.id for item in only_completed.items}


@pytest.mark.asyncio
async def test_get_broadcast_roundtrip(db_session) -> None:
    admin = await _make_user(db_session, role="support_admin")
    u = await _make_user(db_session)
    created = await create_broadcast(
        db_session,
        admin=admin,
        draft=_draft(
            audience=BROADCAST_AUDIENCE_CUSTOM,
            audience_filter={"telegram_ids": [u.telegram_id]},
        ),
    )
    fetched = await get_broadcast(db_session, created.id)
    assert fetched.id == created.id


@pytest.mark.asyncio
async def test_get_broadcast_missing(db_session) -> None:
    with pytest.raises(BroadcastNotFoundError):
        await get_broadcast(db_session, 999_999_999)


@pytest.mark.asyncio
async def test_get_broadcast_stats_aggregates(db_session) -> None:
    admin = await _make_user(db_session, role="support_admin")
    u1 = await _make_user(db_session)
    u2 = await _make_user(db_session)
    u3 = await _make_user(db_session)

    broadcast = await create_broadcast(
        db_session,
        admin=admin,
        draft=_draft(
            audience=BROADCAST_AUDIENCE_CUSTOM,
            audience_filter={
                "telegram_ids": [u1.telegram_id, u2.telegram_id, u3.telegram_id]
            },
        ),
    )
    # Force per-recipient statuses to exercise the aggregation
    recipients = (
        await db_session.execute(
            select(BroadcastRecipient).where(
                BroadcastRecipient.broadcast_id == broadcast.id
            )
        )
    ).scalars().all()
    statuses = [
        RECIPIENT_STATUS_DELIVERED,
        RECIPIENT_STATUS_FAILED,
        RECIPIENT_STATUS_SKIPPED,
    ]
    for r, s in zip(recipients, statuses, strict=True):
        r.status = s
        if s == RECIPIENT_STATUS_DELIVERED:
            r.clicks = 4
    await db_session.flush()

    stats = await get_broadcast_stats(db_session, broadcast.id)
    assert stats.delivered == 1
    assert stats.failed == 1
    assert stats.skipped == 1
    assert stats.pending == 0
    assert stats.clicks == 4
    assert stats.total_recipients == 3


# ---------------------------------------------------------------- worker picker


@pytest.mark.asyncio
async def test_list_due_broadcasts_picks_drafts_and_due_scheduled(db_session) -> None:
    admin = await _make_user(db_session, role="support_admin")
    u = await _make_user(db_session)
    now = datetime.now(UTC)

    draft_b = await create_broadcast(
        db_session,
        admin=admin,
        draft=_draft(
            audience=BROADCAST_AUDIENCE_CUSTOM,
            audience_filter={"telegram_ids": [u.telegram_id]},
        ),
    )

    past = now - timedelta(hours=1)
    future = now + timedelta(hours=1)
    due_scheduled = Broadcast(
        created_by=admin.id,
        text="due",
        audience=BROADCAST_AUDIENCE_ALL,
        status=BROADCAST_STATUS_SCHEDULED,
        scheduled_at=past,
    )
    future_scheduled = Broadcast(
        created_by=admin.id,
        text="future",
        audience=BROADCAST_AUDIENCE_ALL,
        status=BROADCAST_STATUS_SCHEDULED,
        scheduled_at=future,
    )
    fresh_in_progress = Broadcast(
        created_by=admin.id,
        text="fresh active",
        audience=BROADCAST_AUDIENCE_ALL,
        status=BROADCAST_STATUS_IN_PROGRESS,
        started_at=now - timedelta(minutes=1),
        updated_at=now - timedelta(minutes=1),
    )
    stale_in_progress = Broadcast(
        created_by=admin.id,
        text="stale active",
        audience=BROADCAST_AUDIENCE_ALL,
        status=BROADCAST_STATUS_IN_PROGRESS,
        started_at=now - BROADCAST_DRAIN_STALE_AFTER - timedelta(minutes=1),
        updated_at=now - BROADCAST_DRAIN_STALE_AFTER - timedelta(seconds=1),
    )
    db_session.add_all([due_scheduled, future_scheduled, fresh_in_progress, stale_in_progress])
    await db_session.flush()

    due = await list_due_broadcasts(db_session, now=now)
    due_ids = {b.id for b in due}
    assert draft_b.id in due_ids
    assert due_scheduled.id in due_ids
    assert future_scheduled.id not in due_ids
    assert fresh_in_progress.id not in due_ids
    assert stale_in_progress.id in due_ids


# ---------------------------------------------------------------- record_recipient_result


@pytest.mark.asyncio
async def test_record_recipient_result_delivered_bumps_counters(db_session) -> None:
    admin = await _make_user(db_session, role="support_admin")
    u = await _make_user(db_session)
    broadcast = await create_broadcast(
        db_session,
        admin=admin,
        draft=_draft(
            audience=BROADCAST_AUDIENCE_CUSTOM,
            audience_filter={"telegram_ids": [u.telegram_id]},
        ),
    )
    recipient = (
        await db_session.execute(
            select(BroadcastRecipient).where(
                BroadcastRecipient.broadcast_id == broadcast.id
            )
        )
    ).scalars().one()

    await record_recipient_result(
        db_session,
        broadcast=broadcast,
        recipient=recipient,
        delivered=True,
        message_id=42,
    )
    await db_session.refresh(broadcast)
    await db_session.refresh(recipient)
    assert recipient.status == RECIPIENT_STATUS_DELIVERED
    assert recipient.message_id == 42
    assert recipient.attempts == 1
    assert broadcast.sent_count == 1
    assert broadcast.delivered_count == 1
    assert broadcast.failed_count == 0


@pytest.mark.asyncio
async def test_record_recipient_result_failure_sets_last_error(db_session) -> None:
    admin = await _make_user(db_session, role="support_admin")
    u = await _make_user(db_session)
    broadcast = await create_broadcast(
        db_session,
        admin=admin,
        draft=_draft(
            audience=BROADCAST_AUDIENCE_CUSTOM,
            audience_filter={"telegram_ids": [u.telegram_id]},
        ),
    )
    recipient = (
        await db_session.execute(
            select(BroadcastRecipient).where(
                BroadcastRecipient.broadcast_id == broadcast.id
            )
        )
    ).scalars().one()

    await record_recipient_result(
        db_session,
        broadcast=broadcast,
        recipient=recipient,
        delivered=False,
        error="chat_not_found",
    )
    await db_session.refresh(broadcast)
    await db_session.refresh(recipient)
    assert recipient.status == RECIPIENT_STATUS_FAILED
    assert recipient.error == "chat_not_found"
    assert broadcast.failed_count == 1
    assert broadcast.last_error == "chat_not_found"


# ---------------------------------------------------------------- drain


class _FakeTelegramClient:
    """Minimal Telegram client for the worker drain tests.

    The behaviour for each chat_id is taken from ``script`` which maps
    ``chat_id -> list[dict]``.  Each entry is consumed in order; once a
    chat exhausts its script the client falls back to a default
    successful send.  An entry of ``{"raise": "...", "code": N}`` makes
    the call raise :class:`TelegramApiError`.
    """

    def __init__(self, script: dict[int, list[dict[str, Any]]] | None = None) -> None:
        self.script = script or {}
        self.calls: list[dict[str, Any]] = []

    async def _consume(self, chat_id: int, payload: dict[str, Any]) -> Any:
        from app.bot.client import TelegramApiError

        self.calls.append(payload)
        steps = self.script.get(chat_id)
        if steps:
            step = steps.pop(0)
            if "raise" in step:
                raise TelegramApiError(
                    "sendMessage",
                    step["raise"],
                    error_code=int(step.get("code", 400)),
                )
            return step.get("result", {"message_id": chat_id * 10})
        return {"message_id": chat_id * 10}

    async def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        parse_mode: str | None = None,
        disable_web_page_preview: bool | None = True,
        reply_markup: dict[str, Any] | None = None,
    ) -> Any:
        return await self._consume(
            chat_id,
            {
                "method": "send_message",
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "reply_markup": reply_markup,
            },
        )

    async def send_photo(
        self,
        *,
        chat_id: int,
        photo: str,
        caption: str | None = None,
        parse_mode: str | None = None,
        reply_markup: dict[str, Any] | None = None,
    ) -> Any:
        return await self._consume(
            chat_id,
            {
                "method": "send_photo",
                "chat_id": chat_id,
                "photo": photo,
                "caption": caption,
                "parse_mode": parse_mode,
                "reply_markup": reply_markup,
            },
        )

    async def send_video(
        self,
        *,
        chat_id: int,
        video: str,
        caption: str | None = None,
        parse_mode: str | None = None,
        reply_markup: dict[str, Any] | None = None,
    ) -> Any:
        return await self._consume(
            chat_id,
            {
                "method": "send_video",
                "chat_id": chat_id,
                "video": video,
                "caption": caption,
                "parse_mode": parse_mode,
                "reply_markup": reply_markup,
            },
        )


@pytest.mark.asyncio
async def test_drain_broadcast_marks_completed_and_writes_finish_audit(
    db_session,
) -> None:
    admin = await _make_user(db_session, role="support_admin")
    u1 = await _make_user(db_session)
    u2 = await _make_user(db_session)

    broadcast = await create_broadcast(
        db_session,
        admin=admin,
        draft=_draft(
            audience=BROADCAST_AUDIENCE_CUSTOM,
            audience_filter={"telegram_ids": [u1.telegram_id, u2.telegram_id]},
        ),
    )
    await db_session.commit()

    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    client = _FakeTelegramClient()
    drained = await drain_broadcast(
        db_session,
        client,
        broadcast=broadcast,
        rate_limit=50,
        sleeper=fake_sleep,
    )
    await db_session.refresh(drained)
    assert drained.status == BROADCAST_STATUS_COMPLETED
    assert drained.started_at is not None
    assert drained.finished_at is not None
    assert drained.delivered_count == 2
    assert drained.failed_count == 0

    # Two send_message calls, one per recipient
    methods = [c["method"] for c in client.calls]
    assert methods == ["send_message", "send_message"]
    assert sleeps  # rate-limit sleeps actually invoked

    # broadcast.finish audit written
    finish = (
        await db_session.execute(
            select(AdminAuditLog).where(AdminAuditLog.action == BROADCAST_AUDIT_FINISH)
        )
    ).scalars().first()
    assert finish is not None
    assert finish.payload["broadcast_id"] == drained.id
    assert finish.payload["delivered"] == 2


@pytest.mark.asyncio
async def test_drain_broadcast_retries_on_429(db_session) -> None:
    admin = await _make_user(db_session, role="support_admin")
    u = await _make_user(db_session)

    broadcast = await create_broadcast(
        db_session,
        admin=admin,
        draft=_draft(
            audience=BROADCAST_AUDIENCE_CUSTOM,
            audience_filter={"telegram_ids": [u.telegram_id]},
        ),
    )
    await db_session.commit()

    # First call is rate-limited; the worker honours the retry-after hint
    # and the second call succeeds.
    client = _FakeTelegramClient(
        script={
            u.telegram_id: [
                {"raise": "Too Many Requests: retry after 2", "code": 429},
                {"result": {"message_id": 555}},
            ]
        }
    )

    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    drained = await drain_broadcast(
        db_session,
        client,
        broadcast=broadcast,
        rate_limit=50,
        sleeper=fake_sleep,
    )
    await db_session.refresh(drained)
    assert drained.delivered_count == 1
    assert drained.status == BROADCAST_STATUS_COMPLETED

    # Two attempts hit the client; the first sleep is the retry-after,
    # which must respect the parsed delay (>= 2.0s).
    assert len(client.calls) == 2
    assert any(s >= 2.0 for s in sleeps)


@pytest.mark.asyncio
async def test_drain_broadcast_stops_when_cancelled_mid_flight(db_session) -> None:
    admin = await _make_user(db_session, role="support_admin")
    u1 = await _make_user(db_session)
    u2 = await _make_user(db_session)

    broadcast = await create_broadcast(
        db_session,
        admin=admin,
        draft=_draft(
            audience=BROADCAST_AUDIENCE_CUSTOM,
            audience_filter={"telegram_ids": [u1.telegram_id, u2.telegram_id]},
        ),
    )
    # Cancel before drain starts; the worker should not attempt a single send.
    broadcast.status = BROADCAST_STATUS_CANCELLED
    await db_session.commit()

    client = _FakeTelegramClient()

    async def fake_sleep(_seconds: float) -> None:
        return None

    drained = await drain_broadcast(
        db_session,
        client,
        broadcast=broadcast,
        rate_limit=50,
        sleeper=fake_sleep,
    )
    assert drained.status == BROADCAST_STATUS_CANCELLED
    assert client.calls == []


@pytest.mark.asyncio
async def test_concurrent_drains_send_each_recipient_once(db_engine) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    broadcast_id: int | None = None
    user_ids: list[int] = []
    telegram_ids: list[int] = []

    async with factory() as setup:
        admin = await _make_user(setup, username="broadcast-race-admin", role="support_admin")
        users = [
            await _make_user(setup, username="broadcast-race-1"),
            await _make_user(setup, username="broadcast-race-2"),
        ]
        broadcast = await create_broadcast(
            setup,
            admin=admin,
            draft=_draft(
                audience=BROADCAST_AUDIENCE_CUSTOM,
                audience_filter={"telegram_ids": [u.telegram_id for u in users]},
            ),
        )
        await setup.commit()
        broadcast_id = int(broadcast.id)
        user_ids = [int(admin.id), *(int(u.id) for u in users)]
        telegram_ids = [int(u.telegram_id) for u in users]

    first_send_started = asyncio.Event()
    release_first_send = asyncio.Event()
    calls_lock = asyncio.Lock()
    calls: list[tuple[str, int]] = []

    class _BlockingTelegramClient:
        def __init__(self, worker: str) -> None:
            self.worker = worker
            self.calls: list[dict[str, Any]] = []

        async def send_message(
            self,
            *,
            chat_id: int,
            text: str,
            parse_mode: str | None = None,
            disable_web_page_preview: bool | None = True,
            reply_markup: dict[str, Any] | None = None,
        ) -> Any:
            payload = {
                "method": "send_message",
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "reply_markup": reply_markup,
            }
            self.calls.append(payload)
            async with calls_lock:
                calls.append((self.worker, chat_id))
                first_call = len(calls) == 1
                if first_call:
                    first_send_started.set()
            if first_call:
                await release_first_send.wait()
            return {"message_id": chat_id * 10}

    async def fake_sleep(_seconds: float) -> None:
        return None

    async def attempt(worker: str) -> list[dict[str, Any]]:
        assert broadcast_id is not None
        async with factory() as session:
            broadcast = await session.get(Broadcast, broadcast_id)
            assert broadcast is not None
            client = _BlockingTelegramClient(worker)
            await drain_broadcast(
                session,
                client,
                broadcast=broadcast,
                rate_limit=50,
                sleeper=fake_sleep,
            )
            return client.calls

    first: asyncio.Task[list[dict[str, Any]]] | None = None
    second: asyncio.Task[list[dict[str, Any]]] | None = None

    try:
        first = asyncio.create_task(attempt("first"))
        await asyncio.wait_for(first_send_started.wait(), timeout=5)

        second = asyncio.create_task(attempt("second"))
        await asyncio.wait_for(second, timeout=5)

        release_first_send.set()
        await asyncio.wait_for(first, timeout=5)

        delivered_chat_ids = [chat_id for _worker, chat_id in calls]
        assert sorted(delivered_chat_ids) == sorted(telegram_ids)

        async with factory() as verify:
            rows = (
                await verify.execute(
                    select(BroadcastRecipient).where(
                        BroadcastRecipient.broadcast_id == broadcast_id
                    )
                )
            ).scalars().all()
            assert {int(row.telegram_id) for row in rows} == set(telegram_ids)
            assert all(row.status == RECIPIENT_STATUS_DELIVERED for row in rows)
            broadcast = await verify.get(Broadcast, broadcast_id)
            assert broadcast is not None
            assert broadcast.delivered_count == len(telegram_ids)
    finally:
        release_first_send.set()
        for task in (second, first):
            if task is not None and not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        async with factory() as cleanup:
            if user_ids:
                await cleanup.execute(
                    AdminAuditLog.__table__.delete().where(AdminAuditLog.admin_id.in_(user_ids))
                )
            if broadcast_id is not None:
                broadcast = await cleanup.get(Broadcast, broadcast_id)
                if broadcast is not None:
                    await cleanup.delete(broadcast)
            for user_id in user_ids:
                user = await cleanup.get(User, user_id)
                if user is not None:
                    await cleanup.delete(user)
            await cleanup.commit()


# ---------------------------------------------------------------- send_one helpers


@pytest.mark.asyncio
async def test_send_one_uses_send_photo_for_media(db_session) -> None:
    admin = await _make_user(db_session, role="support_admin")
    broadcast = Broadcast(
        created_by=admin.id,
        text="caption",
        audience=BROADCAST_AUDIENCE_ALL,
        media_type="photo",
        media_url="https://example.com/a.jpg",
        buttons=[{"text": "Open", "url": "https://example.com"}],
        parse_mode="HTML",
    )
    client = _FakeTelegramClient()
    result = await send_one(client, broadcast, chat_id=12345)
    assert result.delivered is True
    assert result.message_id == 123_450  # default fake fallback = chat_id * 10
    assert client.calls[0]["method"] == "send_photo"
    assert client.calls[0]["photo"] == "https://example.com/a.jpg"
    assert client.calls[0]["reply_markup"] == {
        "inline_keyboard": [[{"text": "Open", "url": "https://example.com"}]]
    }


@pytest.mark.asyncio
async def test_send_one_returns_retry_after_on_429() -> None:
    class _RaisingClient:
        async def send_message(self, **kwargs: Any) -> Any:
            from app.bot.client import TelegramApiError

            raise TelegramApiError(
                "sendMessage", "Too Many Requests: retry after 7", error_code=429
            )

    broadcast = Broadcast(
        created_by=1,
        text="text",
        audience=BROADCAST_AUDIENCE_ALL,
    )
    result = await send_one(_RaisingClient(), broadcast, chat_id=10)
    assert isinstance(result, TelegramSendResult)
    assert result.delivered is False
    assert result.retry_after == 7.0


def test_retry_after_from_description_parses_seconds() -> None:
    assert _retry_after_from_description("Too Many Requests: retry after 5") == 5.0
    assert _retry_after_from_description("retry after 1.5 seconds") == 1.5
    assert _retry_after_from_description(None) is None
    assert _retry_after_from_description("nope") is None


def test_build_reply_markup_filters_invalid_buttons() -> None:
    out = build_reply_markup(
        [
            {"text": "ok", "url": "https://x"},
            {"text": "cb", "callback_data": "open"},
            {"text": "missing_target"},  # dropped: no url / callback_data
            {"url": "no-text"},  # dropped: no text
            "not-a-dict",  # dropped: wrong type
        ]
    )
    assert out is not None
    assert out["inline_keyboard"] == [
        [{"text": "ok", "url": "https://x"}],
        [{"text": "cb", "callback_data": "open"}],
    ]
    assert build_reply_markup(None) is None
    assert build_reply_markup([]) is None


# ---------------------------------------------------------------- fetch + click


@pytest.mark.asyncio
async def test_fetch_pending_recipients_respects_batch_size(db_session) -> None:
    admin = await _make_user(db_session, role="support_admin")
    u1 = await _make_user(db_session)
    u2 = await _make_user(db_session)
    u3 = await _make_user(db_session)

    broadcast = await create_broadcast(
        db_session,
        admin=admin,
        draft=_draft(
            audience=BROADCAST_AUDIENCE_CUSTOM,
            audience_filter={
                "telegram_ids": [u1.telegram_id, u2.telegram_id, u3.telegram_id]
            },
        ),
    )

    batch = await fetch_pending_recipients(
        db_session, broadcast_id=broadcast.id, batch_size=2
    )
    assert len(batch) == 2
    assert all(r.status == RECIPIENT_STATUS_PENDING for r in batch)


@pytest.mark.asyncio
async def test_record_click_bumps_recipient_and_campaign(db_session) -> None:
    admin = await _make_user(db_session, role="support_admin")
    u = await _make_user(db_session)
    broadcast = await create_broadcast(
        db_session,
        admin=admin,
        draft=_draft(
            audience=BROADCAST_AUDIENCE_CUSTOM,
            audience_filter={"telegram_ids": [u.telegram_id]},
        ),
    )
    await record_click(db_session, broadcast_id=broadcast.id, user_id=u.id)
    await record_click(db_session, broadcast_id=broadcast.id, user_id=u.id)
    await db_session.refresh(broadcast)

    recipient = (
        await db_session.execute(
            select(BroadcastRecipient).where(
                BroadcastRecipient.broadcast_id == broadcast.id,
                BroadcastRecipient.user_id == u.id,
            )
        )
    ).scalars().one()
    assert recipient.clicks == 2
    assert broadcast.clicks_count == 2


@pytest.mark.asyncio
async def test_record_click_noop_for_unknown_recipient(db_session) -> None:
    # Should silently return None even if recipient row is missing.
    await record_click(db_session, broadcast_id=999_999, user_id=999_999)
