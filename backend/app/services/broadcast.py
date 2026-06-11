"""Broadcast service (Phase 3, issue #28).

Powers the CRM "Broadcast" section.  An admin composes a campaign
(text / media / inline buttons) for a target audience and the worker
fans it out via the Telegram Bot API.  This module exposes the SQL
building blocks that both the HTTP layer and the worker share:

* :func:`build_audience_query` — translates an audience selector
  (``all`` / ``premium`` / ``free`` / ``inactive_7d`` / ``custom``) into
  a SQL filter against ``users``.
* :func:`preview_audience` — counts the audience without enumerating it,
  so the composer can show "X users will receive this message".
* :func:`create_broadcast` — persists the campaign row, materialises
  ``broadcast_recipients`` rows, and writes an audit-log entry.
* :func:`cancel_broadcast` — marks a not-yet-finished campaign as
  ``cancelled`` so the worker stops draining its queue.
* :func:`list_broadcasts`, :func:`get_broadcast` — paginated and
  single-row reads for the admin UI.
* :func:`get_broadcast_stats` — derives the headline counters that the
  UI shows on the campaign detail page.

The worker pieces (``send_next_batch``, ``record_recipient_result``)
live in this module too so unit tests can drive them without spinning
up Celery.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Select, and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.admin_audit_log import AdminAuditLog
from app.models.broadcast import (
    BROADCAST_AUDIENCE_ALL,
    BROADCAST_AUDIENCE_CUSTOM,
    BROADCAST_AUDIENCE_FREE,
    BROADCAST_AUDIENCE_INACTIVE_7D,
    BROADCAST_AUDIENCE_PREMIUM,
    BROADCAST_AUDIENCES,
    BROADCAST_STATUS_CANCELLED,
    BROADCAST_STATUS_COMPLETED,
    BROADCAST_STATUS_DRAFT,
    BROADCAST_STATUS_FAILED,
    BROADCAST_STATUS_IN_PROGRESS,
    BROADCAST_STATUS_SCHEDULED,
    RECIPIENT_STATUS_DELIVERED,
    RECIPIENT_STATUS_FAILED,
    RECIPIENT_STATUS_PENDING,
    RECIPIENT_STATUS_SENT,
    RECIPIENT_STATUS_SKIPPED,
    Broadcast,
    BroadcastRecipient,
)
from app.models.user import User

logger = get_logger(__name__)


# ----------------------------------------------------------------- constants

# Telegram Bot API allows 30 messages per second across all chats — we
# stay just under the cap to absorb retries and clock drift.
TELEGRAM_BROADCAST_RATE_LIMIT = 25
BROADCAST_RATE_LIMIT_MAX_RETRIES = 5

# Maximum length of the inline message body (Telegram caps at 4096 chars).
MAX_TEXT_LEN = 4096
MAX_TITLE_LEN = 255
MAX_BUTTONS = 6

# Inactivity threshold used by the ``inactive_7d`` audience selector.
INACTIVE_THRESHOLD_DAYS = 7

DEFAULT_LIMIT = 20
MAX_LIMIT = 200

BROADCAST_AUDIT_CREATE = "broadcast.create"
BROADCAST_AUDIT_CANCEL = "broadcast.cancel"
BROADCAST_AUDIT_FINISH = "broadcast.finish"

# Statuses that can still be cancelled.
CANCELLABLE_STATUSES: frozenset[str] = frozenset(
    {BROADCAST_STATUS_DRAFT, BROADCAST_STATUS_SCHEDULED, BROADCAST_STATUS_IN_PROGRESS}
)

# A worker updates ``Broadcast.updated_at`` after every recipient.  Another
# pass may reclaim an ``in_progress`` campaign only after this quiet period.
BROADCAST_DRAIN_STALE_AFTER = timedelta(minutes=10)


# ----------------------------------------------------------------- exceptions


class BroadcastError(Exception):
    """Base class for broadcast service failures."""


class InvalidBroadcastPayloadError(BroadcastError):
    """Raised when create_broadcast receives malformed input."""


class InvalidAudienceError(BroadcastError):
    """Raised when the audience selector is unknown."""


class BroadcastNotFoundError(BroadcastError):
    """The referenced broadcast does not exist."""


class BroadcastNotCancellableError(BroadcastError):
    """Broadcast is already completed / cancelled / failed."""


class EmptyAudienceError(BroadcastError):
    """The selected audience matched zero users."""


# ----------------------------------------------------------------- dataclasses


@dataclass(frozen=True)
class BroadcastButton:
    text: str
    url: str | None = None
    callback_data: str | None = None

    def to_dict(self) -> dict[str, str]:
        out: dict[str, str] = {"text": self.text}
        if self.url:
            out["url"] = self.url
        elif self.callback_data:
            out["callback_data"] = self.callback_data
        return out


@dataclass(frozen=True)
class BroadcastDraft:
    """Input payload for :func:`create_broadcast`."""

    text: str
    title: str | None = None
    parse_mode: str | None = "HTML"
    media_type: str | None = None  # "photo" | "video" | None
    media_url: str | None = None
    buttons: tuple[BroadcastButton, ...] = ()
    audience: str = BROADCAST_AUDIENCE_ALL
    audience_filter: dict[str, Any] | None = None
    scheduled_at: datetime | None = None


@dataclass(frozen=True)
class BroadcastListPage:
    items: list[Broadcast]
    total: int
    page: int
    limit: int
    has_more: bool = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "has_more", (self.page * self.limit) < self.total)


@dataclass(frozen=True)
class BroadcastStats:
    broadcast: Broadcast
    total_recipients: int
    pending: int
    sent: int
    delivered: int
    failed: int
    skipped: int
    clicks: int


# ----------------------------------------------------------------- audience


def _coerce_audience(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if raw not in BROADCAST_AUDIENCES:
        raise InvalidAudienceError(
            f"unsupported audience={value!r}; expected one of " f"{', '.join(BROADCAST_AUDIENCES)}"
        )
    return raw


def build_audience_query(
    audience: str,
    *,
    audience_filter: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> Select[Any]:
    """Return a ``SELECT users`` statement matching the audience.

    Banned users are always excluded — broadcasts to them would be
    delivered but they cannot respond, and Telegram penalises sends to
    accounts the bot has blocked.  ``custom`` audiences receive a list
    of ``telegram_id``s in ``audience_filter['telegram_ids']`` and we
    intersect that with the live user table so deleted accounts are
    skipped without an error.
    """
    audience = _coerce_audience(audience)
    now = now or datetime.now(UTC)

    stmt = select(User).where(User.is_banned.is_(False))

    if audience == BROADCAST_AUDIENCE_ALL:
        return stmt
    if audience == BROADCAST_AUDIENCE_PREMIUM:
        return stmt.where(User.is_premium.is_(True))
    if audience == BROADCAST_AUDIENCE_FREE:
        return stmt.where(User.is_premium.is_(False))
    if audience == BROADCAST_AUDIENCE_INACTIVE_7D:
        cutoff = now - timedelta(days=INACTIVE_THRESHOLD_DAYS)
        return stmt.where(User.last_active_at < cutoff)
    if audience == BROADCAST_AUDIENCE_CUSTOM:
        if not audience_filter:
            raise InvalidAudienceError("custom audience requires audience_filter")
        telegram_ids = audience_filter.get("telegram_ids")
        user_ids = audience_filter.get("user_ids")
        conditions: list[Any] = []
        if isinstance(telegram_ids, list) and telegram_ids:
            try:
                ids = [int(x) for x in telegram_ids]
            except (TypeError, ValueError) as exc:
                raise InvalidAudienceError("telegram_ids must be a list of integers") from exc
            conditions.append(User.telegram_id.in_(ids))
        if isinstance(user_ids, list) and user_ids:
            try:
                ids = [int(x) for x in user_ids]
            except (TypeError, ValueError) as exc:
                raise InvalidAudienceError("user_ids must be a list of integers") from exc
            conditions.append(User.id.in_(ids))
        if not conditions:
            raise InvalidAudienceError("custom audience requires telegram_ids or user_ids")
        return stmt.where(or_(*conditions))
    raise InvalidAudienceError(f"unsupported audience={audience!r}")


async def preview_audience(
    session: AsyncSession,
    *,
    audience: str,
    audience_filter: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> int:
    """Return how many users match ``audience`` without enumerating them."""
    user_query = build_audience_query(audience, audience_filter=audience_filter, now=now)
    count_stmt = select(func.count()).select_from(user_query.subquery())
    return int((await session.execute(count_stmt)).scalar_one())


# ----------------------------------------------------------------- validation


def _validate_draft(draft: BroadcastDraft) -> BroadcastDraft:
    text = (draft.text or "").strip()
    if not text:
        raise InvalidBroadcastPayloadError("text is required")
    if len(text) > MAX_TEXT_LEN:
        raise InvalidBroadcastPayloadError(f"text exceeds {MAX_TEXT_LEN} characters")

    title = (draft.title or "").strip() or None
    if title and len(title) > MAX_TITLE_LEN:
        title = title[:MAX_TITLE_LEN]

    media_type = (draft.media_type or "").strip().lower() or None
    if media_type and media_type not in ("photo", "video"):
        raise InvalidBroadcastPayloadError(
            f"unsupported media_type={draft.media_type!r}; expected photo|video"
        )
    media_url = (draft.media_url or "").strip() or None
    if media_type and not media_url:
        raise InvalidBroadcastPayloadError(f"media_url is required for media_type={media_type!r}")

    parse_mode = (draft.parse_mode or "").strip() or None
    if parse_mode and parse_mode not in ("HTML", "Markdown", "MarkdownV2"):
        raise InvalidBroadcastPayloadError(f"unsupported parse_mode={parse_mode!r}")

    if len(draft.buttons) > MAX_BUTTONS:
        raise InvalidBroadcastPayloadError(f"too many buttons (max {MAX_BUTTONS})")
    for btn in draft.buttons:
        if not btn.text or not btn.text.strip():
            raise InvalidBroadcastPayloadError("button.text is required")
        if not btn.url and not btn.callback_data:
            raise InvalidBroadcastPayloadError("each button requires url or callback_data")

    audience = _coerce_audience(draft.audience)

    return BroadcastDraft(
        text=text,
        title=title,
        parse_mode=parse_mode,
        media_type=media_type,
        media_url=media_url,
        buttons=draft.buttons,
        audience=audience,
        audience_filter=draft.audience_filter,
        scheduled_at=draft.scheduled_at,
    )


# ----------------------------------------------------------------- create


async def create_broadcast(
    session: AsyncSession,
    *,
    admin: User,
    draft: BroadcastDraft,
    ip_address: str | None = None,
    user_agent: str | None = None,
    now: datetime | None = None,
) -> Broadcast:
    """Persist a new broadcast + recipient rows; write an audit row.

    Caller commits.  Returns the freshly-created :class:`Broadcast` with
    ``total_recipients`` set to the materialised audience size.
    """
    cleaned = _validate_draft(draft)
    now = now or datetime.now(UTC)

    user_query = build_audience_query(
        cleaned.audience,
        audience_filter=cleaned.audience_filter,
        now=now,
    )
    recipient_rows = list(
        (await session.execute(user_query.with_only_columns(User.id, User.telegram_id))).all()
    )
    if not recipient_rows:
        raise EmptyAudienceError("audience matched zero users")

    is_scheduled = cleaned.scheduled_at is not None and cleaned.scheduled_at > now
    status = BROADCAST_STATUS_SCHEDULED if is_scheduled else BROADCAST_STATUS_DRAFT

    broadcast = Broadcast(
        created_by=admin.id,
        title=cleaned.title,
        text=cleaned.text,
        parse_mode=cleaned.parse_mode,
        media_type=cleaned.media_type,
        media_url=cleaned.media_url,
        buttons=[b.to_dict() for b in cleaned.buttons] or None,
        audience=cleaned.audience,
        audience_filter=cleaned.audience_filter,
        status=status,
        scheduled_at=cleaned.scheduled_at if is_scheduled else None,
        total_recipients=len(recipient_rows),
    )
    session.add(broadcast)
    await session.flush()

    session.add_all(
        BroadcastRecipient(
            broadcast_id=broadcast.id,
            user_id=row.id,
            telegram_id=row.telegram_id,
        )
        for row in recipient_rows
    )
    await session.flush()

    session.add(
        AdminAuditLog(
            admin_id=admin.id,
            target_user_id=None,
            action=BROADCAST_AUDIT_CREATE,
            payload={
                "broadcast_id": broadcast.id,
                "audience": broadcast.audience,
                "total_recipients": broadcast.total_recipients,
                "scheduled_at": (
                    broadcast.scheduled_at.isoformat() if broadcast.scheduled_at else None
                ),
                "media_type": broadcast.media_type,
                "title": broadcast.title,
            },
            ip_address=(ip_address or "")[:64] or None,
            user_agent=(user_agent or "")[:512] or None,
        )
    )
    await session.flush()
    logger.info(
        "broadcast.created",
        broadcast_id=broadcast.id,
        admin_id=admin.id,
        audience=broadcast.audience,
        total=broadcast.total_recipients,
        status=broadcast.status,
    )
    return broadcast


# ----------------------------------------------------------------- cancel


async def cancel_broadcast(
    session: AsyncSession,
    *,
    admin: User,
    broadcast_id: int,
    ip_address: str | None = None,
    user_agent: str | None = None,
    now: datetime | None = None,
) -> Broadcast:
    """Mark broadcast as cancelled if not already finished."""
    broadcast = await session.get(Broadcast, broadcast_id)
    if broadcast is None:
        raise BroadcastNotFoundError(f"broadcast {broadcast_id} not found")
    if broadcast.status not in CANCELLABLE_STATUSES:
        raise BroadcastNotCancellableError(
            f"broadcast in status={broadcast.status!r} cannot be cancelled"
        )

    now = now or datetime.now(UTC)
    broadcast.status = BROADCAST_STATUS_CANCELLED
    broadcast.cancelled_at = now
    broadcast.finished_at = now
    await session.flush()

    # Cascade pending recipients to ``skipped`` so the worker stops
    # picking them up on retry.
    await session.execute(
        update(BroadcastRecipient)
        .where(
            BroadcastRecipient.broadcast_id == broadcast_id,
            BroadcastRecipient.status == RECIPIENT_STATUS_PENDING,
        )
        .values(status=RECIPIENT_STATUS_SKIPPED, error="cancelled_by_admin")
    )

    session.add(
        AdminAuditLog(
            admin_id=admin.id,
            target_user_id=None,
            action=BROADCAST_AUDIT_CANCEL,
            payload={
                "broadcast_id": broadcast.id,
                "previous_status": broadcast.status,
            },
            ip_address=(ip_address or "")[:64] or None,
            user_agent=(user_agent or "")[:512] or None,
        )
    )
    await session.flush()
    logger.info(
        "broadcast.cancelled",
        broadcast_id=broadcast.id,
        admin_id=admin.id,
    )
    return broadcast


# ----------------------------------------------------------------- read


async def get_broadcast(session: AsyncSession, broadcast_id: int) -> Broadcast:
    broadcast = await session.get(Broadcast, broadcast_id)
    if broadcast is None:
        raise BroadcastNotFoundError(f"broadcast {broadcast_id} not found")
    return broadcast


async def list_broadcasts(
    session: AsyncSession,
    *,
    status: str | None = None,
    page: int = 1,
    limit: int = DEFAULT_LIMIT,
) -> BroadcastListPage:
    page = max(int(page or 1), 1)
    limit = max(min(int(limit or DEFAULT_LIMIT), MAX_LIMIT), 1)
    offset = (page - 1) * limit

    count_stmt = select(func.count()).select_from(Broadcast)
    rows_stmt = select(Broadcast)
    if status:
        count_stmt = count_stmt.where(Broadcast.status == status)
        rows_stmt = rows_stmt.where(Broadcast.status == status)
    rows_stmt = (
        rows_stmt.order_by(Broadcast.created_at.desc(), Broadcast.id.desc())
        .offset(offset)
        .limit(limit)
    )

    total = int((await session.execute(count_stmt)).scalar_one())
    items = list((await session.execute(rows_stmt)).scalars().all())
    return BroadcastListPage(items=items, total=total, page=page, limit=limit)


async def get_broadcast_stats(session: AsyncSession, broadcast_id: int) -> BroadcastStats:
    broadcast = await get_broadcast(session, broadcast_id)
    stmt = (
        select(BroadcastRecipient.status, func.count())
        .where(BroadcastRecipient.broadcast_id == broadcast_id)
        .group_by(BroadcastRecipient.status)
    )
    rows = (await session.execute(stmt)).all()
    counts = {
        status: 0
        for status in (
            RECIPIENT_STATUS_PENDING,
            RECIPIENT_STATUS_SENT,
            RECIPIENT_STATUS_DELIVERED,
            RECIPIENT_STATUS_FAILED,
            RECIPIENT_STATUS_SKIPPED,
        )
    }
    for status, count in rows:
        counts[status] = int(count)

    clicks_stmt = select(func.coalesce(func.sum(BroadcastRecipient.clicks), 0)).where(
        BroadcastRecipient.broadcast_id == broadcast_id
    )
    clicks = int((await session.execute(clicks_stmt)).scalar_one())

    return BroadcastStats(
        broadcast=broadcast,
        total_recipients=broadcast.total_recipients,
        pending=counts[RECIPIENT_STATUS_PENDING],
        sent=counts[RECIPIENT_STATUS_SENT],
        delivered=counts[RECIPIENT_STATUS_DELIVERED],
        failed=counts[RECIPIENT_STATUS_FAILED],
        skipped=counts[RECIPIENT_STATUS_SKIPPED],
        clicks=clicks,
    )


# ------------------------------------------------------------- worker pieces


async def list_due_broadcasts(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    limit: int = 25,
) -> list[Broadcast]:
    """Return broadcasts ready to drain: drafts, due scheduled, or stale active."""
    now = now or datetime.now(UTC)
    stale_before = now - BROADCAST_DRAIN_STALE_AFTER
    stmt = (
        select(Broadcast)
        .where(
            or_(
                Broadcast.status == BROADCAST_STATUS_DRAFT,
                and_(
                    Broadcast.status == BROADCAST_STATUS_SCHEDULED,
                    Broadcast.scheduled_at.is_not(None),
                    Broadcast.scheduled_at <= now,
                ),
                and_(
                    Broadcast.status == BROADCAST_STATUS_IN_PROGRESS,
                    Broadcast.updated_at <= stale_before,
                ),
            )
        )
        .order_by(Broadcast.created_at.asc(), Broadcast.id.asc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


async def fetch_pending_recipients(
    session: AsyncSession,
    *,
    broadcast_id: int,
    batch_size: int,
) -> list[BroadcastRecipient]:
    """Return the next batch of ``pending`` recipients."""
    stmt = (
        select(BroadcastRecipient)
        .where(
            BroadcastRecipient.broadcast_id == broadcast_id,
            BroadcastRecipient.status == RECIPIENT_STATUS_PENDING,
        )
        .order_by(BroadcastRecipient.id.asc())
        .limit(max(int(batch_size or 1), 1))
    )
    return list((await session.execute(stmt)).scalars().all())


async def mark_broadcast_started(
    session: AsyncSession,
    *,
    broadcast: Broadcast,
    now: datetime | None = None,
) -> bool:
    """Atomically claim ``broadcast`` for one drain worker.

    Concurrent workers can select the same due row before either commits.  The
    conditional ``UPDATE`` makes only one of them own the active drain; a stale
    ``in_progress`` row can still be reclaimed after the heartbeat window.
    """
    now = now or datetime.now(UTC)
    stale_before = now - BROADCAST_DRAIN_STALE_AFTER
    stmt = (
        update(Broadcast)
        .where(
            Broadcast.id == broadcast.id,
            or_(
                Broadcast.status == BROADCAST_STATUS_DRAFT,
                and_(
                    Broadcast.status == BROADCAST_STATUS_SCHEDULED,
                    Broadcast.scheduled_at.is_not(None),
                    Broadcast.scheduled_at <= now,
                ),
                and_(
                    Broadcast.status == BROADCAST_STATUS_IN_PROGRESS,
                    Broadcast.updated_at <= stale_before,
                ),
            ),
        )
        .values(
            status=BROADCAST_STATUS_IN_PROGRESS,
            started_at=func.coalesce(Broadcast.started_at, now),
            updated_at=now,
        )
        .returning(Broadcast.id)
    )
    claimed = (await session.execute(stmt)).scalar_one_or_none() is not None
    await session.flush()
    await session.refresh(broadcast)
    return claimed


async def mark_broadcast_finished(
    session: AsyncSession,
    *,
    broadcast: Broadcast,
    now: datetime | None = None,
    failed: bool = False,
) -> None:
    now = now or datetime.now(UTC)
    broadcast.status = BROADCAST_STATUS_FAILED if failed else BROADCAST_STATUS_COMPLETED
    broadcast.finished_at = now
    await session.flush()


def build_reply_markup(buttons: list[dict] | None) -> dict[str, Any] | None:
    """Convert stored button payload into a Telegram inline_keyboard."""
    if not buttons:
        return None
    rows: list[list[dict[str, Any]]] = []
    for btn in buttons:
        if not isinstance(btn, dict):
            continue
        text = btn.get("text")
        if not isinstance(text, str):
            continue
        entry: dict[str, Any] = {"text": text}
        if "url" in btn and btn.get("url"):
            entry["url"] = str(btn["url"])
        elif "callback_data" in btn and btn.get("callback_data"):
            entry["callback_data"] = str(btn["callback_data"])
        else:
            continue
        rows.append([entry])
    if not rows:
        return None
    return {"inline_keyboard": rows}


async def record_recipient_result(
    session: AsyncSession,
    *,
    broadcast: Broadcast,
    recipient: BroadcastRecipient,
    delivered: bool,
    message_id: int | None = None,
    error: str | None = None,
    skipped: bool = False,
    now: datetime | None = None,
) -> None:
    """Persist the outcome of one Telegram send.

    Counters on the :class:`Broadcast` row are bumped here so an
    operator can refresh the UI mid-run and watch progress.
    """
    now = now or datetime.now(UTC)
    recipient.attempts = (recipient.attempts or 0) + 1
    recipient.updated_at = now
    broadcast.updated_at = now

    if skipped:
        recipient.status = RECIPIENT_STATUS_SKIPPED
        recipient.error = (error or "")[:1024] or None
        broadcast.skipped_count = (broadcast.skipped_count or 0) + 1
    elif delivered:
        recipient.status = RECIPIENT_STATUS_DELIVERED
        recipient.message_id = message_id
        recipient.sent_at = now
        broadcast.sent_count = (broadcast.sent_count or 0) + 1
        broadcast.delivered_count = (broadcast.delivered_count or 0) + 1
    else:
        recipient.status = RECIPIENT_STATUS_FAILED
        recipient.error = (error or "")[:1024] or None
        broadcast.failed_count = (broadcast.failed_count or 0) + 1
        broadcast.last_error = (error or "")[:512] or None

    await session.flush()


# ----------------------------------------------------------------- sender


@dataclass
class TelegramSendResult:
    delivered: bool
    message_id: int | None
    error: str | None
    retry_after: float | None = None


async def send_one(
    client: Any,
    broadcast: Broadcast,
    chat_id: int,
) -> TelegramSendResult:
    """Send the broadcast payload to a single chat.

    The Telegram client interface only requires three async methods:
    ``send_message``, ``send_photo``, ``send_video`` — every Phase-1
    implementation in this repo conforms.  We catch the project's
    :class:`~app.bot.client.TelegramApiError` so any underlying HTTP
    transport stays opaque to the worker.
    """
    from app.bot.client import TelegramApiError

    reply_markup = build_reply_markup(broadcast.buttons)
    try:
        if broadcast.media_type == "photo" and broadcast.media_url:
            result = await client.send_photo(
                chat_id=chat_id,
                photo=broadcast.media_url,
                caption=broadcast.text,
                parse_mode=broadcast.parse_mode,
                reply_markup=reply_markup,
            )
        elif broadcast.media_type == "video" and broadcast.media_url:
            result = await client.send_video(
                chat_id=chat_id,
                video=broadcast.media_url,
                caption=broadcast.text,
                parse_mode=broadcast.parse_mode,
                reply_markup=reply_markup,
            )
        else:
            result = await client.send_message(
                chat_id=chat_id,
                text=broadcast.text,
                parse_mode=broadcast.parse_mode,
                disable_web_page_preview=True,
                reply_markup=reply_markup,
            )
        message_id: int | None = None
        if isinstance(result, dict):
            mid = result.get("message_id")
            if isinstance(mid, int):
                message_id = mid
        return TelegramSendResult(delivered=True, message_id=message_id, error=None)
    except TelegramApiError as exc:
        retry_after = _retry_after_from_description(exc.description)
        return TelegramSendResult(
            delivered=False,
            message_id=None,
            error=exc.description,
            retry_after=retry_after,
        )


def _retry_after_from_description(description: str | None) -> float | None:
    """Parse Telegram's ``Too Many Requests: retry after N`` payload."""
    if not description:
        return None
    text = description.lower()
    marker = "retry after"
    idx = text.find(marker)
    if idx < 0:
        return None
    tail = text[idx + len(marker) :].strip().split()
    if not tail:
        return None
    try:
        return float(tail[0])
    except ValueError:
        return None


async def drain_broadcast(
    session: AsyncSession,
    client: Any,
    *,
    broadcast: Broadcast,
    rate_limit: int = TELEGRAM_BROADCAST_RATE_LIMIT,
    max_rate_limit_retries: int = BROADCAST_RATE_LIMIT_MAX_RETRIES,
    max_batches: int | None = None,
    sleeper: Any = asyncio.sleep,
    now_fn: Any = None,
) -> Broadcast:
    """Drain pending recipients for ``broadcast`` until empty or cancelled.

    The worker mirrors Telegram's 30 msg/sec budget: at most ``rate_limit``
    messages per second.  On HTTP 429 the worker honours the ``retry_after``
    hint embedded in the API description.
    """
    if rate_limit <= 0:
        rate_limit = 1
    max_rate_limit_retries = max(int(max_rate_limit_retries), 0)
    interval = 1.0 / float(rate_limit)
    now_fn = now_fn or (lambda: datetime.now(UTC))

    # Honour an upstream cancel: never flip a CANCELLED campaign back to
    # in-progress just because the worker happened to pick it up.
    await session.refresh(broadcast)
    if broadcast.status == BROADCAST_STATUS_CANCELLED:
        logger.info("broadcast.drain.cancelled_before_start", broadcast_id=broadcast.id)
        return broadcast

    claimed = await mark_broadcast_started(session, broadcast=broadcast, now=now_fn())
    if not claimed:
        logger.info("broadcast.drain.already_claimed", broadcast_id=broadcast.id)
        return broadcast
    await session.commit()

    batches_run = 0
    while True:
        await session.refresh(broadcast)
        if broadcast.status == BROADCAST_STATUS_CANCELLED:
            logger.info("broadcast.drain.cancelled", broadcast_id=broadcast.id)
            return broadcast

        recipients = await fetch_pending_recipients(
            session, broadcast_id=broadcast.id, batch_size=rate_limit
        )
        if not recipients:
            break

        for recipient in recipients:
            await session.refresh(broadcast)
            if broadcast.status == BROADCAST_STATUS_CANCELLED:
                return broadcast
            result = await send_one(client, broadcast, recipient.telegram_id)
            rate_limit_retries = 0
            while (
                not result.delivered
                and result.retry_after is not None
                and rate_limit_retries < max_rate_limit_retries
            ):
                rate_limit_retries += 1
                wait = max(result.retry_after, interval)
                logger.warning(
                    "broadcast.rate_limited",
                    broadcast_id=broadcast.id,
                    retry_after=wait,
                    retry=rate_limit_retries,
                    max_retries=max_rate_limit_retries,
                )
                await sleeper(wait)
                await session.refresh(broadcast)
                if broadcast.status == BROADCAST_STATUS_CANCELLED:
                    return broadcast
                result = await send_one(client, broadcast, recipient.telegram_id)

            if not result.delivered and result.retry_after is not None:
                logger.warning(
                    "broadcast.rate_limit_retries_exhausted",
                    broadcast_id=broadcast.id,
                    retry_after=result.retry_after,
                    max_retries=max_rate_limit_retries,
                )

            await record_recipient_result(
                session,
                broadcast=broadcast,
                recipient=recipient,
                delivered=result.delivered,
                message_id=result.message_id,
                error=result.error,
                now=now_fn(),
            )
            await session.commit()
            await sleeper(interval)

        batches_run += 1
        if max_batches is not None and batches_run >= max_batches:
            break

    await session.refresh(broadcast)
    remaining = await fetch_pending_recipients(session, broadcast_id=broadcast.id, batch_size=1)
    if not remaining and broadcast.status != BROADCAST_STATUS_CANCELLED:
        await mark_broadcast_finished(session, broadcast=broadcast, now=now_fn())
        session.add(
            AdminAuditLog(
                admin_id=broadcast.created_by,
                target_user_id=None,
                action=BROADCAST_AUDIT_FINISH,
                payload={
                    "broadcast_id": broadcast.id,
                    "delivered": broadcast.delivered_count,
                    "failed": broadcast.failed_count,
                    "skipped": broadcast.skipped_count,
                },
            )
        )
        await session.commit()
    return broadcast


# ----------------------------------------------------------------- click


async def record_click(
    session: AsyncSession,
    *,
    broadcast_id: int,
    user_id: int,
) -> None:
    """Bump the per-recipient + campaign click counter.

    Caller commits.  Silently no-ops when the recipient row is missing
    (e.g. a stale ``callback_query`` from a deleted broadcast).
    """
    recipient = (
        await session.execute(
            select(BroadcastRecipient).where(
                BroadcastRecipient.broadcast_id == broadcast_id,
                BroadcastRecipient.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if recipient is None:
        return
    recipient.clicks = (recipient.clicks or 0) + 1
    await session.execute(
        update(Broadcast)
        .where(Broadcast.id == broadcast_id)
        .values(clicks_count=Broadcast.clicks_count + 1)
    )
    await session.flush()
