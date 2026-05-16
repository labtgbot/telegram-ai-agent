"""Telegram Bot integration (Phase 1).

The webhook handler lives in :mod:`app.api.v1.bot`; this package provides the
pieces it composes:

* :mod:`.client`     — thin async wrapper over the Telegram Bot API (httpx).
* :mod:`.commands`   — bot menu definition + ``setMyCommands`` helper.
* :mod:`.fsm`        — Redis-backed FSM for multi-step flows.
* :mod:`.handlers`   — one async function per supported command/callback.
* :mod:`.keyboards`  — inline keyboard builders.
* :mod:`.dispatcher` — entry point that turns an Update into a handler call.
"""
from app.bot.client import TelegramApiError, TelegramClient
from app.bot.commands import BOT_COMMANDS, set_bot_commands
from app.bot.dispatcher import dispatch_update
from app.bot.fsm import RedisFSM

__all__ = [
    "BOT_COMMANDS",
    "RedisFSM",
    "TelegramApiError",
    "TelegramClient",
    "dispatch_update",
    "set_bot_commands",
]
