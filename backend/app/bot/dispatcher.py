"""Update dispatcher: turn a raw Telegram Update dict into a handler call.

The dispatcher is intentionally tiny — no decorator-based registration, no
middleware stack — so unit tests don't need to mock a framework.  Errors
from individual handlers are caught and reported back to the user; the
dispatcher always returns normally so the webhook can return ``200 OK``
(Telegram retries non-2xx responses, which would amplify any failure).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.client import TelegramApiError, TelegramClient
from app.bot.handlers import (
    COMMAND_HANDLERS,
    HandlerContext,
    handle_callback_query,
    handle_pre_checkout_query,
    handle_successful_payment,
)
from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def _extract_command(text: str | None, *, bot_username: str | None) -> str | None:
    """Return the command name (without ``/`` or ``@bot`` suffix) or ``None``."""
    if not text or not text.startswith("/"):
        return None
    first = text.split(maxsplit=1)[0]
    name = first[1:]
    if "@" in name:
        name, _, mention = name.partition("@")
        if bot_username and mention and mention.lower() != bot_username.lower():
            return None
    return name.lower() or None


async def dispatch_update(
    update: dict[str, Any],
    *,
    settings: Settings,
    client: TelegramClient,
    session: AsyncSession,
) -> None:
    """Route ``update`` to the appropriate handler."""
    ctx = HandlerContext(
        update=update,
        settings=settings,
        client=client,
        session=session,
    )

    if "callback_query" in update:
        ctx.callback_query = update["callback_query"]
        await _safe_call(ctx, handle_callback_query, label="callback")
        return

    if "pre_checkout_query" in update:
        await _safe_call(ctx, handle_pre_checkout_query, label="pre_checkout")
        return

    message = update.get("message") or update.get("edited_message")
    if not message:
        logger.info("bot.update.ignored", keys=list(update.keys()))
        return
    ctx.message = message

    if "successful_payment" in message:
        await _safe_call(ctx, handle_successful_payment, label="successful_payment")
        return

    command = _extract_command(message.get("text"), bot_username=settings.telegram_bot_username)
    if command is None:
        # Phase 1 only handles commands; free-form messages will route to AI in Phase 2.
        await _safe_call(ctx, _handle_free_text, label="free_text")
        return

    handler = COMMAND_HANDLERS.get(command)
    if handler is None:
        await _safe_call(ctx, _handle_unknown_command, label=f"cmd:{command}")
        return

    await _safe_call(ctx, handler, label=f"cmd:{command}")


async def _safe_call(ctx: HandlerContext, handler: Any, *, label: str) -> None:
    try:
        await handler(ctx)
    except TelegramApiError as exc:
        logger.warning("bot.dispatch.telegram_error", label=label, error=str(exc))
    except SQLAlchemyError as exc:
        logger.exception("bot.dispatch.db_error", label=label, error=str(exc))
        await _send_safe(ctx, "Storage hiccup — please try again in a moment.")
    except Exception as exc:  # noqa: BLE001 — defensive catch-all
        logger.exception("bot.dispatch.unhandled", label=label, error=str(exc))
        await _send_safe(ctx, "Something went wrong on our side — please try again later.")


async def _send_safe(ctx: HandlerContext, text: str) -> None:
    if ctx.chat_id is None:
        return
    try:
        await ctx.client.send_message(ctx.chat_id, text)
    except TelegramApiError as exc:
        logger.warning("bot.dispatch.notify_failed", error=str(exc))


async def _handle_free_text(ctx: HandlerContext) -> None:
    if ctx.chat_id is None:
        return
    await ctx.client.send_message(
        ctx.chat_id,
        "Send /help to see what I can do — AI chat is coming in Phase 2.",
    )


async def _handle_unknown_command(ctx: HandlerContext) -> None:
    if ctx.chat_id is None:
        return
    await ctx.client.send_message(
        ctx.chat_id,
        "Unknown command. Send /help to see what's available.",
    )
