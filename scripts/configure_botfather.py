"""Apply production BotFather metadata via the Bot API.

The Telegram Bot API exposes the same surface BotFather drives — once we
own a bot token we can configure description, short description, menu
button (Mini App entry point) and the command list from code instead of
typing them into BotFather by hand. That keeps the production bot's
identity reproducible across re-deployments.

Usage (from repo root)::

    TELEGRAM_BOT_TOKEN=123:abc \
    TELEGRAM_MINI_APP_URL=https://app.example.com \
        python -m scripts.configure_botfather

Optional environment variables:

* ``TELEGRAM_BOT_USERNAME`` — sanity-checked against ``getMe`` so we
  cannot apply the wrong bot's profile by accident.
* ``TELEGRAM_BOTFATHER_DRY_RUN=1`` — print every call that would be made
  without invoking the Bot API.
* ``TELEGRAM_BOTFATHER_LANGUAGE_CODES`` — comma-separated list of BCP-47
  codes. Defaults to ``""`` (the bot-wide fallback) plus ``ru,en``.

Idempotent: Telegram's setter endpoints return ``ok=true`` even when the
value is unchanged.

Reference: https://core.telegram.org/bots/api#available-methods
"""
from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.bot.client import TelegramApiError, TelegramClient  # noqa: E402
from app.bot.commands import BOT_COMMANDS  # noqa: E402

DEFAULT_LANGUAGE_CODES = ("", "ru", "en")

PRODUCTION_DESCRIPTION = (
    "Telegram AI Agent — генерация изображений, видео, текста, голоса, "
    "поиск в интернете и анализ документов. Покупка токенов через "
    "Telegram Stars. Цены на 50% ниже аналогов."
)

PRODUCTION_SHORT_DESCRIPTION = (
    "AI-агент в Telegram: текст, картинки, видео, голос. Оплата Stars."
)

MENU_BUTTON_TEXT = "Открыть Mini App"


@dataclass(frozen=True)
class BotFatherConfig:
    bot_token: str
    mini_app_url: str
    expected_username: str | None
    language_codes: tuple[str, ...]
    dry_run: bool

    @classmethod
    def from_env(cls) -> "BotFatherConfig":
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            raise SystemExit(
                "TELEGRAM_BOT_TOKEN is required. Export the production token "
                "from your secret store before running this script."
            )
        mini_app_url = os.environ.get("TELEGRAM_MINI_APP_URL", "").strip()
        if not mini_app_url.startswith("https://"):
            raise SystemExit(
                "TELEGRAM_MINI_APP_URL must be an https:// URL (Telegram "
                f"rejects http and custom schemes). Got: {mini_app_url!r}"
            )
        codes_raw = os.environ.get("TELEGRAM_BOTFATHER_LANGUAGE_CODES")
        if codes_raw is None:
            language_codes = DEFAULT_LANGUAGE_CODES
        else:
            language_codes = tuple(
                code.strip() for code in codes_raw.split(",")
            )
        return cls(
            bot_token=token,
            mini_app_url=mini_app_url,
            expected_username=(
                os.environ.get("TELEGRAM_BOT_USERNAME", "").lstrip("@").strip()
                or None
            ),
            language_codes=language_codes,
            dry_run=os.environ.get("TELEGRAM_BOTFATHER_DRY_RUN") == "1",
        )


async def _call(client: TelegramClient, method: str, **payload: object) -> object:
    """Wrap ``client.call`` so transient ``description`` errors are visible.

    Telegram returns ``ok=true`` when the value matches the current one,
    so idempotent retries don't surface as failures.
    """
    return await client.call(method, **payload)


async def apply(config: BotFatherConfig) -> None:
    client = TelegramClient(config.bot_token)
    try:
        if config.dry_run:
            print("[dry-run] would call getMe")
        else:
            me = await _call(client, "getMe")
            username = (me or {}).get("username") if isinstance(me, dict) else None
            print(f"connected as @{username}")
            if (
                config.expected_username
                and username
                and username.lower() != config.expected_username.lower()
            ):
                raise SystemExit(
                    f"Refusing to update @{username}: TELEGRAM_BOT_USERNAME "
                    f"expects @{config.expected_username}."
                )

        for lang in config.language_codes:
            await _apply_for_language(client, config, lang)

        await _apply_menu_button(client, config)
    finally:
        await client.aclose()


async def _apply_for_language(
    client: TelegramClient,
    config: BotFatherConfig,
    language_code: str,
) -> None:
    label = language_code or "<default>"
    print(f"--- language: {label}")

    commands = [c.to_api() for c in BOT_COMMANDS]
    if config.dry_run:
        print(f"[dry-run] setMyCommands ({len(commands)} commands, lang={label})")
    else:
        await _call(
            client,
            "setMyCommands",
            commands=commands,
            language_code=language_code or None,
        )
        print(f"  setMyCommands ✓ ({len(commands)} commands)")

    if config.dry_run:
        print(f"[dry-run] setMyDescription (lang={label})")
    else:
        await _call(
            client,
            "setMyDescription",
            description=PRODUCTION_DESCRIPTION,
            language_code=language_code or None,
        )
        print("  setMyDescription ✓")

    if config.dry_run:
        print(f"[dry-run] setMyShortDescription (lang={label})")
    else:
        await _call(
            client,
            "setMyShortDescription",
            short_description=PRODUCTION_SHORT_DESCRIPTION,
            language_code=language_code or None,
        )
        print("  setMyShortDescription ✓")


async def _apply_menu_button(
    client: TelegramClient, config: BotFatherConfig
) -> None:
    print("--- menu button (default scope)")
    menu_button = {
        "type": "web_app",
        "text": MENU_BUTTON_TEXT,
        "web_app": {"url": config.mini_app_url},
    }
    if config.dry_run:
        print(f"[dry-run] setChatMenuButton → {menu_button}")
        return
    try:
        await _call(client, "setChatMenuButton", menu_button=menu_button)
        print(f"  setChatMenuButton ✓ ({config.mini_app_url})")
    except TelegramApiError as exc:
        raise SystemExit(
            f"setChatMenuButton failed: {exc.description}. Check that the "
            "Mini App URL is reachable over HTTPS with a valid certificate."
        ) from exc


def main() -> None:
    config = BotFatherConfig.from_env()
    asyncio.run(apply(config))
    print("done — production bot metadata applied.")


if __name__ == "__main__":
    main()
