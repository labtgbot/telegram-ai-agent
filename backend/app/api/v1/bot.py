"""Telegram Bot webhook endpoint.

Telegram POSTs every update to ``POST /api/v1/bot/webhook``.  We verify the
``X-Telegram-Bot-Api-Secret-Token`` header (set when registering the webhook
via ``setWebhook``) before dispatching, then always return ``200 OK`` — even
if the handler raised — so Telegram won't retry the same update in a tight
loop.
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel

from app.auth.dependencies import SessionDep, SettingsDep
from app.bot.client import TelegramClient
from app.bot.dispatcher import dispatch_update
from app.core.logging import get_logger

router = APIRouter(prefix="/bot", tags=["bot"])
logger = get_logger(__name__)


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


def _check_secret(expected: str, received: str | None) -> None:
    if not expected:
        return  # secret disabled in this environment
    if not received or received != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_webhook_secret",
        )


@router.post(
    "/webhook",
    response_model=WebhookAck,
    summary="Telegram Bot API webhook entry point",
)
async def telegram_webhook(
    settings: SettingsDep,
    session: SessionDep,
    client: BotClientDep,
    update: dict[str, Any],
    x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None,
) -> WebhookAck:
    """Receive a Telegram Update and dispatch it."""
    _check_secret(settings.telegram_webhook_secret, x_telegram_bot_api_secret_token)

    update_id = update.get("update_id")
    logger.info("bot.webhook.received", update_id=update_id)

    try:
        await dispatch_update(
            update,
            settings=settings,
            client=client,
            session=session,
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
