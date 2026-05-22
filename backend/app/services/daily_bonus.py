"""Daily-bonus retention loop with streak progression.

The user-facing contract (issue #22):

* A user may claim **one** bonus per UTC date.
* Two consecutive UTC days form a streak.  The reward grows along the
  configured ladder (``10 → 12 → 15 → 20`` by default), capped at the
  last value.  A skipped day resets the streak back to day one.
* The bonus is credited through :class:`TokenService` so it shows up in
  ``transactions`` like every other token credit (``transaction_type =
  "bonus"``, ``package_name = "daily_bonus"``).
* Status is read often (every Mini App open) and writes are rare, so we
  cache the hot fields in Redis with a 48-hour TTL while the DB stays
  the source of truth on cache miss.

Idempotency
-----------

Three layers guard against double-credit:

1. **Service-level guard** — :meth:`DailyBonusService.claim` reads the
   latest claim for the user and short-circuits when the row already
   exists for "today".  This wins the common case.
2. **DB UNIQUE constraint** — ``daily_bonus_claims (user_id, claim_date)``
   raises an ``IntegrityError`` if two requests race the service guard.
   The service catches it and turns it into an
   :class:`AlreadyClaimedError`, leaving the transaction rolled back
   so the caller may continue using the session.
3. **Transaction marker** — the bonus row in ``transactions`` carries
   ``payment_id = "daily_bonus:user:{id}:date:{YYYY-MM-DD}"`` plus a
   partial unique index from migration ``0003_payment_idempotency`` to
   reject duplicates even across concurrent processes.

CRM configuration
-----------------

The ladder defaults to :attr:`Settings.daily_bonus_ladder` (env var
``DAILY_BONUS_AMOUNTS``).  Operators can override it at runtime by
upserting the ``daily_bonus.amounts`` row in ``admin_settings`` — a
JSONB list of positive integers.  The same table carries the
``daily_bonus.enabled`` master switch so the loop can be paused without
a deploy.  Settings reads are tolerant: a malformed override falls back
to the env-default and logs a warning.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Final

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.admin_setting import AdminSetting
from app.models.daily_bonus_claim import DailyBonusClaim
from app.services.balance_cache import get_default_balance_cache
from app.services.token_service import TokenService, UserNotFoundError

logger = get_logger(__name__)


DAILY_BONUS_PACKAGE: Final[str] = "daily_bonus"
DAILY_BONUS_PAYMENT_PREFIX: Final[str] = "daily_bonus:"
ADMIN_SETTING_AMOUNTS: Final[str] = "daily_bonus.amounts"
ADMIN_SETTING_ENABLED: Final[str] = "daily_bonus.enabled"

REDIS_KEY_PREFIX: Final[str] = "daily_bonus:user:"
# ~48h so a same-day status read after midnight UTC still hits cache,
# while a long-skipped streak does not poison the cache forever.
REDIS_TTL_SECONDS: Final[int] = 48 * 60 * 60


# ----------------------------------------------------------------- exceptions


class DailyBonusError(Exception):
    """Base for service-level errors."""


class DailyBonusDisabledError(DailyBonusError):
    """Master switch in ``admin_settings`` (or env) is off."""


class AlreadyClaimedError(DailyBonusError):
    """The user has already claimed today's bonus (UTC)."""

    def __init__(self, *, next_available_at: datetime) -> None:
        super().__init__("daily bonus already claimed today")
        self.next_available_at = next_available_at


# ------------------------------------------------------------------- types


@dataclass(frozen=True)
class DailyBonusStatus:
    """What the Mini App / bot needs to render the claim card."""

    available: bool
    enabled: bool
    streak_day: int
    next_amount: int
    last_claim_date: date | None
    next_available_at: datetime
    amounts: tuple[int, ...]


@dataclass(frozen=True)
class DailyBonusClaimResult:
    amount: int
    streak_day: int
    new_balance: int
    transaction_id: int
    claim_date: date
    next_available_at: datetime


@dataclass(frozen=True)
class _LatestClaim:
    """Internal snapshot of the latest persisted claim."""

    claim_date: date
    streak_day: int


@dataclass(frozen=True)
class _RuntimeConfig:
    enabled: bool
    amounts: tuple[int, ...] = field(default=(10,))

    def amount_for_streak(self, streak_day: int) -> int:
        if not self.amounts:
            return 0
        idx = max(1, int(streak_day)) - 1
        if idx >= len(self.amounts):
            idx = len(self.amounts) - 1
        return int(self.amounts[idx])


# ---------------------------------------------------------------- helpers


def _today_utc(now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).astimezone(UTC).date()


def _next_midnight_utc(today: date) -> datetime:
    return datetime.combine(today + timedelta(days=1), time(0, 0, 0), tzinfo=UTC)


def _payment_id(user_id: int, claim_date: date) -> str:
    return (
        f"{DAILY_BONUS_PAYMENT_PREFIX}user:{user_id}"
        f":date:{claim_date.isoformat()}"
    )


def _coerce_amounts(raw: Any) -> tuple[int, ...] | None:
    """Parse the admin-stored ladder.  Accept ``[10, 12, ...]`` or ``"10,12"``."""
    if raw is None:
        return None
    values: list[int] = []
    if isinstance(raw, (list, tuple)):
        for item in raw:
            try:
                v = int(item)
            except (TypeError, ValueError):
                return None
            if v <= 0:
                return None
            values.append(v)
    elif isinstance(raw, str):
        for chunk in raw.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                v = int(chunk)
            except ValueError:
                return None
            if v <= 0:
                return None
            values.append(v)
    else:
        return None
    return tuple(values) if values else None


async def load_runtime_config(session: AsyncSession) -> _RuntimeConfig:
    """Read the master switch + ladder, layering admin overrides on env."""
    settings = get_settings()
    enabled = bool(settings.daily_bonus_enabled)
    amounts = settings.daily_bonus_ladder

    try:
        rows = (
            await session.execute(
                select(AdminSetting.setting_key, AdminSetting.setting_value).where(
                    AdminSetting.setting_key.in_(
                        (ADMIN_SETTING_AMOUNTS, ADMIN_SETTING_ENABLED)
                    )
                )
            )
        ).all()
    except Exception as exc:  # noqa: BLE001 — never break callers on a config read
        logger.warning("daily_bonus.config_load_failed", error=str(exc))
        rows = []

    for key, value in rows:
        if key == ADMIN_SETTING_ENABLED:
            if isinstance(value, bool):
                enabled = value
            elif isinstance(value, Mapping) and "enabled" in value:
                enabled = bool(value["enabled"])
            elif isinstance(value, (int, str)):
                enabled = bool(value) and str(value).lower() not in {"0", "false", ""}
        elif key == ADMIN_SETTING_AMOUNTS:
            payload: Any = value
            if isinstance(value, Mapping) and "amounts" in value:
                payload = value["amounts"]
            parsed = _coerce_amounts(payload)
            if parsed is not None:
                amounts = parsed
            else:
                logger.warning(
                    "daily_bonus.bad_amounts_override",
                    got=type(value).__name__,
                )
    return _RuntimeConfig(enabled=enabled, amounts=amounts)


def _streak_day_for(*, today: date, latest: _LatestClaim | None) -> int:
    """Streak position for a claim made on ``today``.

    * No prior claim → 1.
    * Last claim was *yesterday* → previous + 1 (streak continues).
    * Anything else (including same day, which is a logic error here) →
      1 (streak reset).
    """
    if latest is None:
        return 1
    if latest.claim_date == today - timedelta(days=1):
        return latest.streak_day + 1
    return 1


# ------------------------------------------------------------------- service


class DailyBonusService:
    """Read + claim daily bonuses with Redis cache + DB ledger."""

    def __init__(self, session: AsyncSession, redis: Redis | None = None) -> None:
        self.session = session
        self.redis = redis

    # ------------------------------------------------------------- queries

    async def status(self, user_id: int, *, now: datetime | None = None) -> DailyBonusStatus:
        """Compute the user's claim status without mutating state.

        Tries Redis first; on miss reads the latest claim row.  The
        result is *not* re-cached here — that happens after a
        successful claim, so stale cache entries cannot cause a
        double-claim.
        """
        when = now or datetime.now(UTC)
        today = _today_utc(when)
        config = await load_runtime_config(self.session)

        latest = await self._read_latest_from_cache(user_id)
        if latest is None:
            latest = await self._read_latest_from_db(user_id)

        already_today = latest is not None and latest.claim_date == today
        if already_today:
            assert latest is not None
            return DailyBonusStatus(
                available=False,
                enabled=config.enabled,
                streak_day=latest.streak_day,
                next_amount=config.amount_for_streak(latest.streak_day + 1),
                last_claim_date=latest.claim_date,
                next_available_at=_next_midnight_utc(today),
                amounts=config.amounts,
            )

        next_streak = _streak_day_for(today=today, latest=latest)
        return DailyBonusStatus(
            available=config.enabled,
            enabled=config.enabled,
            streak_day=latest.streak_day if latest is not None else 0,
            next_amount=config.amount_for_streak(next_streak),
            last_claim_date=latest.claim_date if latest is not None else None,
            next_available_at=_next_midnight_utc(today),
            amounts=config.amounts,
        )

    # -------------------------------------------------------------- claim

    async def claim(
        self, user_id: int, *, now: datetime | None = None
    ) -> DailyBonusClaimResult:
        """Credit today's bonus.  Raises :class:`AlreadyClaimedError` on retry."""
        when = now or datetime.now(UTC)
        today = _today_utc(when)
        config = await load_runtime_config(self.session)
        if not config.enabled:
            raise DailyBonusDisabledError("daily bonus is disabled")

        # Service-level guard: cheap if cache is warm, falls back to DB.
        latest = await self._read_latest_from_cache(user_id)
        if latest is None or latest.claim_date < today - timedelta(days=1):
            latest = await self._read_latest_from_db(user_id)
        if latest is not None and latest.claim_date == today:
            raise AlreadyClaimedError(next_available_at=_next_midnight_utc(today))

        streak_day = _streak_day_for(today=today, latest=latest)
        amount = config.amount_for_streak(streak_day)
        if amount <= 0:
            # Configuration anomaly — treat as disabled rather than crash.
            raise DailyBonusDisabledError(
                "daily bonus amount resolved to 0 — check admin settings"
            )

        token_service = TokenService(self.session, get_default_balance_cache())
        try:
            credit = await token_service.add(
                user_id=user_id,
                amount=amount,
                transaction_type="bonus",
                package_name=DAILY_BONUS_PACKAGE,
                payment_id=_payment_id(user_id, today),
                payment_status="completed",
                meta={"streak_day": streak_day, "claim_date": today.isoformat()},
            )
        except UserNotFoundError:
            raise

        claim = DailyBonusClaim(
            user_id=user_id,
            claim_date=today,
            streak_day=streak_day,
            amount=amount,
            transaction_id=credit.transaction_id,
        )
        self.session.add(claim)
        try:
            await self.session.flush()
        except IntegrityError:
            # Lost the race: another request inserted the row first.
            # Roll back so the caller can reuse the session, then
            # surface the standard "already claimed" error.
            await self.session.rollback()
            raise AlreadyClaimedError(
                next_available_at=_next_midnight_utc(today)
            ) from None

        await self._write_latest_to_cache(
            user_id, _LatestClaim(claim_date=today, streak_day=streak_day)
        )
        logger.info(
            "daily_bonus.claimed",
            user_id=user_id,
            amount=amount,
            streak_day=streak_day,
            claim_date=today.isoformat(),
            transaction_id=credit.transaction_id,
        )
        return DailyBonusClaimResult(
            amount=amount,
            streak_day=streak_day,
            new_balance=credit.new_balance,
            transaction_id=credit.transaction_id,
            claim_date=today,
            next_available_at=_next_midnight_utc(today),
        )

    # --------------------------------------------------------- persistence

    async def _read_latest_from_db(self, user_id: int) -> _LatestClaim | None:
        stmt = (
            select(DailyBonusClaim.claim_date, DailyBonusClaim.streak_day)
            .where(DailyBonusClaim.user_id == user_id)
            .order_by(DailyBonusClaim.claim_date.desc())
            .limit(1)
        )
        row = (await self.session.execute(stmt)).first()
        if row is None:
            return None
        return _LatestClaim(claim_date=row[0], streak_day=int(row[1]))

    async def _read_latest_from_cache(self, user_id: int) -> _LatestClaim | None:
        if self.redis is None:
            return None
        try:
            payload = await self.redis.get(self._redis_key(user_id))
        except Exception as exc:  # noqa: BLE001 — Redis hiccups must not break claims
            logger.warning("daily_bonus.cache_read_failed", error=str(exc))
            return None
        if not payload:
            return None
        try:
            data = json.loads(payload) if isinstance(payload, str) else payload
            return _LatestClaim(
                claim_date=date.fromisoformat(data["claim_date"]),
                streak_day=int(data["streak_day"]),
            )
        except (ValueError, KeyError, TypeError) as exc:
            logger.warning("daily_bonus.cache_parse_failed", error=str(exc))
            return None

    async def _write_latest_to_cache(
        self, user_id: int, snapshot: _LatestClaim
    ) -> None:
        if self.redis is None:
            return
        try:
            await self.redis.set(
                self._redis_key(user_id),
                json.dumps(
                    {
                        "claim_date": snapshot.claim_date.isoformat(),
                        "streak_day": snapshot.streak_day,
                    }
                ),
                ex=REDIS_TTL_SECONDS,
            )
        except Exception as exc:  # noqa: BLE001 — cache writes are best-effort
            logger.warning("daily_bonus.cache_write_failed", error=str(exc))

    @staticmethod
    def _redis_key(user_id: int) -> str:
        return f"{REDIS_KEY_PREFIX}{user_id}"


__all__ = [
    "ADMIN_SETTING_AMOUNTS",
    "ADMIN_SETTING_ENABLED",
    "AlreadyClaimedError",
    "DAILY_BONUS_PACKAGE",
    "DAILY_BONUS_PAYMENT_PREFIX",
    "DailyBonusClaimResult",
    "DailyBonusDisabledError",
    "DailyBonusError",
    "DailyBonusService",
    "DailyBonusStatus",
    "load_runtime_config",
]
