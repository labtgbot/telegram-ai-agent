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

    async def send_photo(
        self,
        chat_id: int,
        photo: str,
        *,
        caption: str | None = None,
        parse_mode: str | None = "HTML",
        reply_markup: dict[str, Any] | None = None,
    ) -> Any:
        """Send a photo by URL (or ``file_id``).

        Uploading raw bytes is not exposed in Phase 2 because every
        Composio image toolkit returns a fetchable URL — Telegram can
        ingest it directly via ``photo`` set to the URL.
        """
        return await self.call(
            "sendPhoto",
            chat_id=chat_id,
            photo=photo,
            caption=caption,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )

    async def send_video(
        self,
        chat_id: int,
        video: str,
        *,
        caption: str | None = None,
        parse_mode: str | None = "HTML",
        duration: int | None = None,
        supports_streaming: bool | None = True,
        reply_markup: dict[str, Any] | None = None,
    ) -> Any:
        """Send a video by URL (or ``file_id``).

        Mirrors :meth:`send_photo` — the Composio video toolkit returns a
        fetchable URL so Telegram can ingest it directly. ``duration`` and
        ``supports_streaming`` are forwarded as Bot API kwargs when set.
        """
        return await self.call(
            "sendVideo",
            chat_id=chat_id,
            video=video,
            caption=caption,
            parse_mode=parse_mode,
            duration=duration,
            supports_streaming=supports_streaming,
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

    # ---------------------------------------------------------------- payments

    async def send_invoice(
        self,
        chat_id: int,
        *,
        title: str,
        description: str,
        payload: str,
        currency: str,
        prices: list[dict[str, Any]],
        provider_token: str = "",
        start_parameter: str | None = None,
        photo_url: str | None = None,
        protect_content: bool | None = None,
        subscription_period: int | None = None,
    ) -> Any:
        """Send an invoice message to ``chat_id``.

        Stars invoices set ``currency='XTR'`` and ``provider_token=''``.
        ``prices`` is a list of LabeledPrice dicts: ``[{"label": "...",
        "amount": stars_count}]``.
        """
        return await self.call(
            "sendInvoice",
            chat_id=chat_id,
            title=title,
            description=description,
            payload=payload,
            provider_token=provider_token,
            currency=currency,
            prices=prices,
            start_parameter=start_parameter,
            photo_url=photo_url,
            protect_content=protect_content,
            subscription_period=subscription_period,
        )

    async def create_invoice_link(
        self,
        *,
        title: str,
        description: str,
        payload: str,
        currency: str,
        prices: list[dict[str, Any]],
        provider_token: str = "",
        photo_url: str | None = None,
        subscription_period: int | None = None,
    ) -> str:
        """Create a Telegram invoice link (``t.me/$...``) for ``payload``.

        Used by ``POST /api/v1/payment/create-invoice`` because the
        endpoint must return something the Mini App can open — a chat-id
        is not available there.  Returns the URL string.
        """
        result = await self.call(
            "createInvoiceLink",
            title=title,
            description=description,
            payload=payload,
            provider_token=provider_token,
            currency=currency,
            prices=prices,
            photo_url=photo_url,
            subscription_period=subscription_period,
        )
        if not isinstance(result, str):
            raise TelegramApiError(
                "createInvoiceLink",
                f"unexpected result type: {type(result).__name__}",
            )
        return result

    async def answer_pre_checkout_query(
        self,
        pre_checkout_query_id: str,
        *,
        ok: bool,
        error_message: str | None = None,
    ) -> Any:
        """Confirm or reject a pre-checkout query.

        Telegram requires this to be sent within 10 seconds; the
        webhook handler must therefore avoid heavy work before calling
        it.
        """
        return await self.call(
            "answerPreCheckoutQuery",
            pre_checkout_query_id=pre_checkout_query_id,
            ok=ok,
            error_message=error_message if not ok else None,
        )
