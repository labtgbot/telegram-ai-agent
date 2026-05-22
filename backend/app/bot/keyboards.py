"""Inline keyboard builders shared between handlers."""
from __future__ import annotations

from typing import Any


def main_menu(*, mini_app_url: str | None = None) -> dict[str, Any]:
    """Inline keyboard shown after ``/start`` and from ``/help``."""
    row1: list[dict[str, Any]] = [
        {"text": "💬 Chat", "callback_data": "menu:chat"},
        {"text": "💰 Balance", "callback_data": "menu:balance"},
    ]
    row2: list[dict[str, Any]] = [
        {"text": "🛒 Buy tokens", "callback_data": "menu:buy"},
        {"text": "👤 Profile", "callback_data": "menu:profile"},
    ]
    row3: list[dict[str, Any]] = [
        {"text": "🎁 Daily bonus", "callback_data": "menu:bonus"},
    ]
    rows: list[list[dict[str, Any]]] = [row1, row2, row3]
    if mini_app_url:
        rows.append([{"text": "🚀 Open Mini App", "web_app": {"url": mini_app_url}}])
    return {"inline_keyboard": rows}


def balance_actions() -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "🛒 Buy tokens", "callback_data": "menu:buy"},
                {"text": "🔗 Invite friends", "callback_data": "menu:referral"},
            ],
        ],
    }


def referral_share(referral_link: str) -> dict[str, Any]:
    share_url = (
        "https://t.me/share/url?"
        f"url={referral_link}&text=Try%20this%20Telegram%20AI%20Agent%21"
    )
    return {
        "inline_keyboard": [
            [{"text": "📤 Share with friends", "url": share_url}],
        ],
    }
