"""Async wrapper around the Telegram Bot API.

Only the methods Phase 1 needs are exposed: ``sendMessage``,
``editMessageText``, ``answerCallbackQuery`` and ``setMyCommands``.

The client owns its own :class:`httpx.AsyncClient` so the FastAPI app can
share one instance across requests; pass an ``httpx.AsyncClient`` in tests
to intercept outbound calls without monkeypatching.
"""
from __future__ import annotations

from typing import Any

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)


class TelegramApiError(RuntimeError):
    """Raised when the Bot API responds with ``ok: false`` or HTTP error."""

    def __init__(self, method: str, description: str, *, error_code: int | None = None) -> None:
        super().__init__(f"{method}: {description}")
        self.method = method
        self.description = description
        self.error_code = error_code


class TelegramClient:
    """Lightweight Bot API client.

    The client never raises on non-200 HTTP responses by default — the
    Telegram API surfaces business errors as ``{"ok": false}`` payloads with
    a ``description`` field.  We translate those into :class:`TelegramApiError`
    so callers can branch on the human-readable reason.
    """

    def __init__(
        self,
        bot_token: str,
        *,
        base_url: str = "https://api.telegram.org",
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 10.0,
    ) -> None:
        if not bot_token:
            raise ValueError("bot_token is required")
        self._bot_token = bot_token
        self._base_url = base_url.rstrip("/")
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(timeout=timeout)

    @property
    def base_url(self) -> str:
        return f"{self._base_url}/bot{self._bot_token}"

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def call(self, method: str, **payload: Any) -> Any:
        """POST ``method`` with the given JSON payload and return ``result``.

        ``None`` values are stripped so callers can pass optional parameters
        unconditionally.  Raises :class:`TelegramApiError` on failure.
        """
        url = f"{self.base_url}/{method}"
        body = {k: v for k, v in payload.items() if v is not None}
        try:
            response = await self._client.post(url, json=body)
        except httpx.HTTPError as exc:
            raise TelegramApiError(method, f"transport error: {exc}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise TelegramApiError(
                method,
                f"invalid JSON (status={response.status_code})",
            ) from exc

        if not isinstance(data, dict) or not data.get("ok"):
            description = (
                data.get("description") if isinstance(data, dict) else "unknown error"
            )
            error_code = data.get("error_code") if isinstance(data, dict) else None
            logger.warning(
                "telegram.api_error",
                method=method,
                error_code=error_code,
                description=description,
            )
            raise TelegramApiError(
                method, str(description), error_code=error_code
            )
        return data.get("result")

    # ---------------------------------------------------------------- helpers

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        parse_mode: str | None = "HTML",
        disable_web_page_preview: bool | None = True,
        reply_markup: dict[str, Any] | None = None,
    ) -> Any:
        return await self.call(
            "sendMessage",
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_web_page_preview,
            reply_markup=reply_markup,
        )

    async def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        *,
        parse_mode: str | None = "HTML",
        disable_web_page_preview: bool | None = True,
        reply_markup: dict[str, Any] | None = None,
    ) -> Any:
        return await self.call(
            "editMessageText",
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_web_page_preview,
            reply_markup=reply_markup,
        )

    async def answer_callback_query(
        self,
        callback_query_id: str,
        *,
        text: str | None = None,
        show_alert: bool = False,
    ) -> Any:
        return await self.call(
            "answerCallbackQuery",
            callback_query_id=callback_query_id,
            text=text,
            show_alert=show_alert,
        )

    async def set_my_commands(
        self,
        commands: list[dict[str, str]],
        *,
        language_code: str | None = None,
        scope: dict[str, Any] | None = None,
    ) -> Any:
        return await self.call(
            "setMyCommands",
            commands=commands,
            scope=scope,
            language_code=language_code,
        )
