"""Telegram Bot webhook endpoint.

Telegram POSTs every update to ``POST /api/v1/bot/webhook``.  We verify the
``X-Telegram-Bot-Api-Secret-Token`` header (set when registering the webhook
via ``setWebhook``) and claim the Telegram ``update_id`` in Redis before
dispatching. Duplicate updates and handler failures return ``200 OK`` so
Telegram does not re-run non-idempotent side effects; an unavailable
idempotency store returns ``503`` before dispatch so Telegram can retry later.
"""

from __future__ import annotations

import hmac
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.api.v1.generate import ComposioClientDep
from app.auth.dependencies import SessionDep, SettingsDep
from app.bot.client import TelegramClient
from app.bot.dispatcher import dispatch_update
from app.core.logging import get_logger
from app.core.redis import get_redis

router = APIRouter(prefix="/bot", tags=["bot"])
logger = get_logger(__name__)
UPDATE_IDEMPOTENCY_KEY_PREFIX = "bot:webhook:update"


class WebhookAck(BaseModel):
    ok: bool = True


_bot_client_singleton: TelegramClient | None = None


def get_bot_client() -> TelegramClient:
    """Return a lazily-created shared :class:`TelegramClient`."""
    global _bot_client_singleton
    if _bot_client_singleton is None:
        from app.core.config import get_settings

        settings = get_settings()
        if not settings.telegram_bot_token:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="bot_token_not_configured",
            )
        _bot_client_singleton = TelegramClient(
            settings.telegram_bot_token,
            base_url=settings.telegram_api_base_url,
        )
    return _bot_client_singleton


async def close_bot_client() -> None:
    global _bot_client_singleton
    if _bot_client_singleton is not None:
        await _bot_client_singleton.aclose()
        _bot_client_singleton = None


def reset_bot_client() -> None:
    """Drop the cached client without closing it (test helper)."""
    global _bot_client_singleton
    _bot_client_singleton = None


BotClientDep = Annotated[TelegramClient, Depends(get_bot_client)]


def _redis_dep() -> Redis:
    return get_redis()


RedisDep = Annotated[Redis, Depends(_redis_dep)]


def _check_secret(expected: str, received: str | None) -> None:
    if not expected:
        return  # secret disabled in this environment
    if not received or not hmac.compare_digest(expected, received):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_webhook_secret",
        )


def _coerce_update_id(raw: Any) -> int | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    return None


def _update_idempotency_key(update_id: int) -> str:
    return f"{UPDATE_IDEMPOTENCY_KEY_PREFIX}:{update_id}"


async def _claim_update_id(redis: Redis, update_id: int, *, ttl_seconds: int) -> bool:
    ttl = max(1, int(ttl_seconds))
    return bool(await redis.set(_update_idempotency_key(update_id), "1", ex=ttl, nx=True))


@router.post(
    "/webhook",
    response_model=WebhookAck,
    summary="Telegram Bot API webhook entry point",
)
async def telegram_webhook(
    settings: SettingsDep,
    session: SessionDep,
    client: BotClientDep,
    composio: ComposioClientDep,
    redis: RedisDep,
    update: dict[str, Any],
    x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None,
) -> WebhookAck:
    """Receive a Telegram Update and dispatch it."""
    _check_secret(settings.telegram_webhook_secret, x_telegram_bot_api_secret_token)

    update_id = _coerce_update_id(update.get("update_id"))
    logger.info("bot.webhook.received", update_id=update_id)
    if update_id is not None:
        try:
            claimed = await _claim_update_id(
                redis,
                update_id,
                ttl_seconds=settings.telegram_update_idempotency_ttl_seconds,
            )
        except RedisError as exc:
            logger.exception("bot.webhook.idempotency_failed", update_id=update_id, error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="idempotency_store_unavailable",
            ) from exc
        if not claimed:
            logger.info("bot.webhook.duplicate", update_id=update_id)
            return WebhookAck()

    try:
        await dispatch_update(
            update,
            settings=settings,
            client=client,
            session=session,
            composio=composio,
        )
        try:
            await session.commit()
        except Exception as exc:  # noqa: BLE001 — rollback below logs cause
            logger.exception("bot.webhook.commit_failed", error=str(exc))
            await session.rollback()
    except Exception as exc:  # noqa: BLE001 — dispatcher already logged
        logger.exception("bot.webhook.unhandled", error=str(exc))
        await session.rollback()

    return WebhookAck()
