"""Command + callback handlers for the Telegram bot.

Each handler is an ``async`` function that receives a :class:`HandlerContext`
and is responsible for replying via the :class:`TelegramClient`.  Handlers
never raise — recoverable errors are reported back to the user, programming
errors bubble to the dispatcher which logs and replies with a generic
"please try again" message.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.client import TelegramClient
from app.bot.commands import BOT_COMMANDS
from app.bot.keyboards import balance_actions, main_menu, referral_share
from app.core.config import Settings
from app.core.logging import get_logger
from app.services.bot_users import register_or_update_user
from app.services.users import find_user_by_telegram_id

logger = get_logger(__name__)


@dataclass
class HandlerContext:
    """Everything a handler needs to do its job.

    ``message`` is set for command messages; ``callback_query`` is set for
    inline-button taps.  The dispatcher fills exactly one of them.
    """

    update: dict[str, Any]
    settings: Settings
    client: TelegramClient
    session: AsyncSession
    message: dict[str, Any] | None = None
    callback_query: dict[str, Any] | None = None

    @property
    def chat_id(self) -> int | None:
        msg = self.message or (self.callback_query or {}).get("message")
        if not msg:
            return None
        chat = msg.get("chat") or {}
        return chat.get("id")

    @property
    def from_user(self) -> dict[str, Any] | None:
        if self.callback_query:
            return self.callback_query.get("from")
        if self.message:
            return self.message.get("from")
        return None


# ----------------------------------------------------------------- formatting

def _format_balance_text(token_balance: int, is_premium: bool) -> str:
    premium = " · ⭐ Premium" if is_premium else ""
    return (
        "💰 <b>Your balance</b>\n"
        f"Tokens available: <b>{token_balance}</b>{premium}\n\n"
        "Tap <i>Buy tokens</i> to top up or <i>Invite friends</i> to earn more."
    )


def _format_help_text() -> str:
    lines = ["<b>Available commands</b>"]
    for c in BOT_COMMANDS:
        lines.append(f"• /{c.command} — {c.description}")
    lines.append("")
    lines.append("Need a hand? Tap a button below to get started.")
    return "\n".join(lines)


def _build_referral_link(bot_username: str, referral_code: str) -> str:
    if not bot_username:
        return f"start=REF:{referral_code}"
    return f"https://t.me/{bot_username}?start={referral_code}"


def _parse_start_payload(text: str | None) -> str | None:
    if not text:
        return None
    parts = text.strip().split(maxsplit=1)
    if len(parts) < 2:
        return None
    return parts[1].strip() or None


# ----------------------------------------------------------------- commands


async def handle_start(ctx: HandlerContext) -> None:
    if ctx.chat_id is None or ctx.from_user is None:
        return

    payload = _parse_start_payload((ctx.message or {}).get("text"))
    result = await register_or_update_user(
        ctx.session,
        telegram_user=ctx.from_user,
        referral_payload=payload,
        signup_bonus_tokens=ctx.settings.telegram_signup_bonus_tokens,
        super_admin_ids=ctx.settings.super_admin_ids,
    )

    name = (result.user.first_name or "friend").strip() or "friend"
    if result.created:
        greeting = (
            f"👋 Welcome, {name}!\n"
            f"You received <b>{result.bonus_credited} tokens</b> "
            "as a signup bonus."
        )
        if result.referrer:
            inviter = result.referrer.first_name or result.referrer.username or "a friend"
            greeting += f"\n\nReferred by <b>{inviter}</b> — thank you both!"
    else:
        greeting = f"👋 Welcome back, {name}!\nYour balance: <b>{result.user.token_balance}</b> tokens."

    await ctx.client.send_message(
        ctx.chat_id,
        greeting,
        reply_markup=main_menu(mini_app_url=ctx.settings.telegram_mini_app_url or None),
    )


async def handle_help(ctx: HandlerContext) -> None:
    if ctx.chat_id is None:
        return
    await ctx.client.send_message(
        ctx.chat_id,
        _format_help_text(),
        reply_markup=main_menu(mini_app_url=ctx.settings.telegram_mini_app_url or None),
    )


async def handle_balance(ctx: HandlerContext) -> None:
    if ctx.chat_id is None or ctx.from_user is None:
        return
    user = await find_user_by_telegram_id(ctx.session, int(ctx.from_user["id"]))
    if user is None:
        await ctx.client.send_message(
            ctx.chat_id,
            "I don't recognise you yet — send /start to register.",
        )
        return
    await ctx.client.send_message(
        ctx.chat_id,
        _format_balance_text(user.token_balance, user.is_premium),
        reply_markup=balance_actions(),
    )


async def handle_buy(ctx: HandlerContext) -> None:
    if ctx.chat_id is None:
        return
    await ctx.client.send_message(
        ctx.chat_id,
        (
            "🛒 <b>Token packages</b>\n"
            "Payments via Telegram Stars are launching in Phase 2.\n"
            "Use /balance to check what you have and /referral to earn more in the meantime."
        ),
    )


async def handle_profile(ctx: HandlerContext) -> None:
    if ctx.chat_id is None or ctx.from_user is None:
        return
    user = await find_user_by_telegram_id(ctx.session, int(ctx.from_user["id"]))
    if user is None:
        await ctx.client.send_message(
            ctx.chat_id,
            "I don't recognise you yet — send /start to register.",
        )
        return
    username_line = f"@{user.username}" if user.username else "—"
    text = (
        "👤 <b>Your profile</b>\n"
        f"Name: {user.first_name or '—'}\n"
        f"Username: {username_line}\n"
        f"Language: {user.language_code or '—'}\n"
        f"Balance: <b>{user.token_balance}</b> tokens\n"
        f"Total spent: {user.total_tokens_spent}\n"
        f"Total requests: {user.total_requests}\n"
        f"Referral code: <code>{user.referral_code}</code>"
    )
    await ctx.client.send_message(ctx.chat_id, text)


async def handle_referral(ctx: HandlerContext) -> None:
    if ctx.chat_id is None or ctx.from_user is None:
        return
    user = await find_user_by_telegram_id(ctx.session, int(ctx.from_user["id"]))
    if user is None:
        await ctx.client.send_message(
            ctx.chat_id,
            "I don't recognise you yet — send /start to register.",
        )
        return
    link = _build_referral_link(ctx.settings.telegram_bot_username, user.referral_code)
    text = (
        "🔗 <b>Invite friends</b>\n"
        f"Share this link to earn bonus tokens when friends sign up:\n\n"
        f"<code>{link}</code>"
    )
    await ctx.client.send_message(
        ctx.chat_id,
        text,
        reply_markup=referral_share(link),
    )


# ----------------------------------------------------------------- callbacks


_CALLBACK_TO_COMMAND = {
    "menu:balance": handle_balance,
    "menu:buy": handle_buy,
    "menu:profile": handle_profile,
    "menu:referral": handle_referral,
    "menu:chat": None,  # handled inline
}


async def handle_callback_query(ctx: HandlerContext) -> None:
    if ctx.callback_query is None:
        return
    data = (ctx.callback_query.get("data") or "").strip()
    try:
        await ctx.client.answer_callback_query(ctx.callback_query["id"])
    except Exception as exc:  # noqa: BLE001 — ack failures are non-fatal
        logger.warning("bot.callback.ack_failed", error=str(exc))

    if data == "menu:chat":
        if ctx.chat_id is not None:
            await ctx.client.send_message(
                ctx.chat_id,
                "💬 Just type your question — AI chat lands in Phase 2.",
            )
        return

    handler = _CALLBACK_TO_COMMAND.get(data)
    if handler is None:
        logger.info("bot.callback.unknown", data=data)
        return
    await handler(ctx)


# ----------------------------------------------------------------- registry

COMMAND_HANDLERS = {
    "start": handle_start,
    "help": handle_help,
    "balance": handle_balance,
    "buy": handle_buy,
    "profile": handle_profile,
    "referral": handle_referral,
}
