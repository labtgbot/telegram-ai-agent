"""Bot menu definition + ``setMyCommands`` helper.

The same list drives both Telegram's command menu and the ``/help`` text so
the two cannot drift apart.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.bot.client import TelegramApiError, TelegramClient
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class BotCommand:
    command: str
    description: str

    def to_api(self) -> dict[str, str]:
        return {"command": self.command, "description": self.description}


BOT_COMMANDS: tuple[BotCommand, ...] = (
    BotCommand("start", "Запустить бота и получить бонус"),
    BotCommand("balance", "Показать баланс токенов"),
    BotCommand("buy", "Купить пакет токенов"),
    BotCommand("image", "Сгенерировать изображение по описанию"),
    BotCommand("profile", "Мой профиль"),
    BotCommand("referral", "Реферальная ссылка"),
    BotCommand("help", "Справка по командам"),
)


async def set_bot_commands(client: TelegramClient) -> bool:
    """Register :data:`BOT_COMMANDS` with Telegram.

    Returns ``True`` on success, ``False`` on Bot API errors (never raises:
    a failed ``setMyCommands`` should not bring the whole app down).
    """
    payload = [c.to_api() for c in BOT_COMMANDS]
    try:
        await client.set_my_commands(payload)
    except TelegramApiError as exc:
        logger.warning("bot.set_commands_failed", error=str(exc))
        return False
    logger.info("bot.commands_registered", count=len(payload))
    return True
