"""Regression tests for bot-side generation rate limiting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.bot import handlers as handlers_module
from app.bot.handlers import HandlerContext, handle_ask, handle_image, handle_video
from app.models.user import User
from app.services.image_generation import ImageGenerationResult
from app.services.rate_limit_config import PLAN_FREE
from app.services.rate_limiter import RateLimitedError
from app.services.text_generation import TextGenerationResult
from app.services.video_generation import VideoJobView


@dataclass
class _Settings:
    telegram_mini_app_url: str = ""


@dataclass
class _LimiterCall:
    plan: str
    identifier: str
    action: str


_COMPOSIO = object()


def _user() -> User:
    return User(
        id=7,
        telegram_id=4242,
        username="alice",
        first_name="Alice",
        referral_code="REF4242",
        is_banned=False,
        is_premium=False,
        role="user",
    )


def _client() -> AsyncMock:
    client = AsyncMock()
    client.send_message = AsyncMock(return_value={"message_id": 1})
    client.send_photo = AsyncMock(return_value={"message_id": 2})
    client.send_video = AsyncMock(return_value={"message_id": 3})
    return client


def _ctx(*, text: str, client: AsyncMock, composio: Any | None = _COMPOSIO) -> HandlerContext:
    return HandlerContext(
        update={"update_id": 1},
        settings=_Settings(),  # type: ignore[arg-type]
        client=client,
        session=AsyncMock(),
        composio=composio,  # type: ignore[arg-type]
        message={
            "chat": {"id": 99},
            "from": {"id": 4242, "first_name": "Alice"},
            "text": text,
        },
    )


def _install_blocking_limiter(monkeypatch: pytest.MonkeyPatch) -> list[_LimiterCall]:
    calls: list[_LimiterCall] = []

    async def fake_find_user(session: Any, telegram_id: int) -> User | None:
        assert telegram_id == 4242
        return _user()

    async def fake_load_rate_limits(session: Any) -> object:
        return object()

    async def fake_resolve_plan(session: Any, user: User | None) -> str:
        assert user is not None
        return PLAN_FREE

    class _BlockingLimiter:
        def __init__(self, redis: Any, config: Any) -> None:
            self.redis = redis
            self.config = config

        async def consume(
            self,
            *,
            plan: str,
            identifier: str,
            action: str,
        ) -> object:
            calls.append(_LimiterCall(plan=plan, identifier=identifier, action=action))
            raise RateLimitedError(
                plan=plan,
                action=action,
                quota_key=f"{action}_per_day",
                limit=1,
                retry_after=60,
                reset_after=60,
            )

    monkeypatch.setattr(handlers_module, "find_user_by_telegram_id", fake_find_user)
    monkeypatch.setattr(
        handlers_module,
        "load_rate_limits",
        fake_load_rate_limits,
        raising=False,
    )
    monkeypatch.setattr(
        handlers_module,
        "resolve_plan_for_user",
        fake_resolve_plan,
        raising=False,
    )
    monkeypatch.setattr(handlers_module, "get_redis", lambda: object())
    monkeypatch.setattr(handlers_module, "RateLimiter", _BlockingLimiter, raising=False)
    return calls


def _install_user_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_find_user(session: Any, telegram_id: int) -> User | None:
        assert telegram_id == 4242
        return _user()

    monkeypatch.setattr(handlers_module, "find_user_by_telegram_id", fake_find_user)


def _install_quota_tracker(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    quota_calls: list[str] = []

    async def fake_consume_generation_rate_limit(
        ctx: HandlerContext,
        *,
        user: User,
        action: str,
    ) -> bool:
        quota_calls.append(action)
        return True

    monkeypatch.setattr(
        handlers_module,
        "_consume_generation_rate_limit",
        fake_consume_generation_rate_limit,
    )
    return quota_calls


@pytest.mark.asyncio
async def test_handle_image_does_not_consume_quota_when_composio_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_user_lookup(monkeypatch)
    quota_calls = _install_quota_tracker(monkeypatch)
    client = _client()

    await handle_image(_ctx(text="/image a cat", client=client, composio=None))

    assert quota_calls == []
    client.send_photo.assert_not_awaited()
    client.send_message.assert_awaited_once_with(
        99,
        "Image generation is temporarily unavailable. Please try again later.",
    )


@pytest.mark.asyncio
async def test_handle_ask_does_not_consume_quota_when_composio_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_user_lookup(monkeypatch)
    quota_calls = _install_quota_tracker(monkeypatch)
    client = _client()

    await handle_ask(_ctx(text="/ask hello", client=client, composio=None))

    assert quota_calls == []
    client.send_message.assert_awaited_once_with(
        99,
        "AI chat is temporarily unavailable. Please try again later.",
    )


@pytest.mark.asyncio
async def test_handle_video_does_not_consume_quota_when_composio_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_user_lookup(monkeypatch)
    quota_calls = _install_quota_tracker(monkeypatch)
    client = _client()

    await handle_video(_ctx(text="/video a cat clip", client=client, composio=None))

    assert quota_calls == []
    client.send_video.assert_not_awaited()
    client.send_message.assert_awaited_once_with(
        99,
        "Video generation is temporarily unavailable. Please try again later.",
    )


@pytest.mark.asyncio
async def test_handle_image_replies_with_upgrade_message_when_rate_limited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limiter_calls = _install_blocking_limiter(monkeypatch)
    generation_calls: list[dict[str, Any]] = []

    class _ImageService:
        def __init__(self, session: Any, composio: Any) -> None:
            return None

        async def generate(self, **kwargs: Any) -> ImageGenerationResult:
            generation_calls.append(dict(kwargs))
            return ImageGenerationResult(
                user_id=7,
                prompt=kwargs["prompt"],
                quality="standard",
                aspect_ratio="1:1",
                tokens_spent=30,
                new_balance=70,
                result_url="https://img.test/cat.png",
                composio_tool="image_gen",
                mcp_server=None,
                processing_time_ms=1,
                usage_log_id=10,
                transaction_id=20,
            )

    monkeypatch.setattr(handlers_module, "ImageGenerationService", _ImageService)
    client = _client()

    await handle_image(_ctx(text="/image a cat", client=client))

    assert limiter_calls == [_LimiterCall(plan=PLAN_FREE, identifier="4242", action="image")]
    assert generation_calls == []
    client.send_photo.assert_not_awaited()
    client.send_message.assert_awaited_once()
    args, kwargs = client.send_message.await_args
    assert args[0] == 99
    assert "limit" in args[1].lower()
    assert "pro" in args[1].lower()
    assert kwargs["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "buy:pro_monthly"


@pytest.mark.asyncio
async def test_handle_ask_replies_with_upgrade_message_when_rate_limited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limiter_calls = _install_blocking_limiter(monkeypatch)
    generation_calls: list[dict[str, Any]] = []

    class _TextService:
        def __init__(self, session: Any, composio: Any, *, history: Any) -> None:
            return None

        async def generate(self, **kwargs: Any) -> TextGenerationResult:
            generation_calls.append(dict(kwargs))
            return TextGenerationResult(
                user_id=7,
                prompt=kwargs["prompt"],
                mode=kwargs["mode"],
                text="ok",
                tokens_spent=1,
                new_balance=99,
                composio_tool="gemini",
                mcp_server=None,
                processing_time_ms=1,
                usage_log_id=10,
                transaction_id=20,
                request_id=kwargs["request_id"],
                thread_id=kwargs["thread_id"],
            )

    monkeypatch.setattr(
        handlers_module,
        "_build_chat_history",
        lambda session, user: object(),
    )
    monkeypatch.setattr(handlers_module, "TextGenerationService", _TextService)
    client = _client()

    await handle_ask(_ctx(text="/ask hello", client=client))

    assert limiter_calls == [_LimiterCall(plan=PLAN_FREE, identifier="4242", action="text")]
    assert generation_calls == []
    client.send_message.assert_awaited_once()
    args, kwargs = client.send_message.await_args
    assert args[0] == 99
    assert "limit" in args[1].lower()
    assert "pro" in args[1].lower()
    assert kwargs["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "buy:pro_monthly"


@pytest.mark.asyncio
async def test_handle_video_replies_with_upgrade_message_when_rate_limited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limiter_calls = _install_blocking_limiter(monkeypatch)
    generation_calls: list[dict[str, Any]] = []

    class _VideoService:
        def __init__(self, session: Any, composio: Any) -> None:
            return None

        async def create(self, **kwargs: Any) -> VideoJobView:
            generation_calls.append(dict(kwargs))
            now = datetime.now(UTC)
            return VideoJobView(
                id=1,
                user_id=7,
                request_id=kwargs["request_id"],
                tariff=kwargs["tariff"],
                duration_s=5,
                prompt=kwargs["prompt"],
                style=None,
                reference_image_url=None,
                status="queued",
                tokens_cost=100,
                provider_job_id="prov-1",
                composio_tool="video_gen",
                mcp_server=None,
                result_url=None,
                error_code=None,
                error_message=None,
                transaction_id=20,
                refund_transaction_id=None,
                usage_log_id=10,
                attempts=0,
                created_at=now,
                updated_at=now,
                completed_at=None,
            )

    monkeypatch.setattr(handlers_module, "VideoGenerationService", _VideoService)
    client = _client()

    await handle_video(_ctx(text="/video a cat clip", client=client))

    assert limiter_calls == [_LimiterCall(plan=PLAN_FREE, identifier="4242", action="video")]
    assert generation_calls == []
    client.send_video.assert_not_awaited()
    client.send_message.assert_awaited_once()
    args, kwargs = client.send_message.await_args
    assert args[0] == 99
    assert "limit" in args[1].lower()
    assert "pro" in args[1].lower()
    assert kwargs["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "buy:pro_monthly"
