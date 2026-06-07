"""FastAPI-level regression tests for authenticated rate limiting."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Annotated, Any
from urllib.parse import urlencode

import pytest
from fastapi import Depends, FastAPI, Request
from httpx import ASGITransport, AsyncClient

from app.api import rate_limit as rate_limit_module
from app.api.v1 import generate as generate_module
from app.auth.dependencies import (
    _settings_dep,
    get_current_user_from_init_data,
)
from app.core.config import Settings
from app.core.database import get_session as real_get_session
from app.models.user import User
from app.services.rate_limit_config import PLAN_PREMIUM
from app.services.rate_limiter import RateLimitResult
from app.services.text_generation import MODE_BASIC, TextGenerationResult

BOT_TOKEN = "1234567890:TEST-AAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


class _FakeSession:
    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None

    async def flush(self) -> None:
        return None

    def add(self, obj: Any) -> None:
        return None


@dataclass
class _ConsumedCall:
    plan: str
    identifier: str
    action: str


class _RecordingLimiter:
    def __init__(self) -> None:
        self.calls: list[_ConsumedCall] = []

    async def consume(
        self,
        *,
        plan: str,
        identifier: str,
        action: str,
    ) -> RateLimitResult:
        self.calls.append(_ConsumedCall(plan=plan, identifier=identifier, action=action))
        return RateLimitResult(
            allowed=True,
            plan=plan,
            action=action,
            quota_key="per_hour",
            limit=100,
            remaining=99,
            reset_after=3600,
            retry_after=0,
        )


class _FakeTextService:
    async def generate(
        self,
        *,
        user_id: int,
        prompt: str,
        mode: str,
        system_prompt: str | None,
        temperature: float,
        max_tokens: int,
        thread_id: str | None,
        request_id: str,
    ) -> TextGenerationResult:
        return TextGenerationResult(
            user_id=user_id,
            prompt=prompt,
            mode=mode,
            text="ok",
            tokens_spent=1,
            new_balance=99,
            composio_tool="fake",
            mcp_server=None,
            processing_time_ms=1,
            usage_log_id=10,
            transaction_id=20,
            request_id=request_id,
            thread_id=thread_id,
        )


def _settings() -> Settings:
    return Settings(
        app_env="test",
        telegram_bot_token=BOT_TOKEN,
        telegram_init_data_max_age=3600,
        metrics_enabled=False,
    )


def _user() -> User:
    return User(
        id=7,
        telegram_id=4242,
        username="alice",
        first_name="Alice",
        referral_code="REF4242",
        is_banned=False,
        is_premium=True,
        role="user",
    )


async def _yield_session():
    yield _FakeSession()


def _build_init_data(telegram_id: int = 4242) -> str:
    user = {"id": telegram_id, "first_name": "Alice", "username": "alice"}
    pairs = [
        ("query_id", "AAA"),
        ("user", json.dumps(user, separators=(",", ":"))),
        ("auth_date", str(int(time.time()))),
    ]
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(pairs, key=lambda p: p[0]))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    pairs.append(("hash", digest))
    return urlencode(pairs)


def _wire_auth(app: FastAPI, monkeypatch: pytest.MonkeyPatch, user: User) -> None:
    async def fake_upsert(session, *, telegram_user, super_admin_ids):  # type: ignore[no-untyped-def]
        assert int(telegram_user["id"]) == user.telegram_id
        return user, False

    from app.auth import dependencies as deps

    monkeypatch.setattr(deps, "upsert_telegram_user", fake_upsert)
    app.dependency_overrides[real_get_session] = _yield_session
    app.dependency_overrides[_settings_dep] = _settings


async def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_init_data_auth_populates_request_state(monkeypatch) -> None:
    user = _user()
    app = FastAPI()
    _wire_auth(app, monkeypatch, user)

    @app.get("/state")
    async def state(
        request: Request,
        current_user: Annotated[User, Depends(get_current_user_from_init_data)],
    ) -> dict[str, Any]:
        return {
            "user_id": current_user.id,
            "state_user_id": getattr(request.state, "user_id", None),
            "same_state_user": getattr(request.state, "user", None) is current_user,
        }

    async with await _client(app) as client:
        resp = await client.get(
            "/state",
            headers={"X-Telegram-Init-Data": _build_init_data()},
        )

    assert resp.status_code == 200
    assert resp.json() == {
        "user_id": user.id,
        "state_user_id": user.id,
        "same_state_user": True,
    }


@pytest.mark.asyncio
async def test_authenticated_generate_request_uses_user_plan(
    monkeypatch,
) -> None:
    user = _user()
    limiter = _RecordingLimiter()

    async def fake_get_rate_limiter():
        return limiter

    async def fake_resolve_plan(session, current_user):  # type: ignore[no-untyped-def]
        assert current_user is user
        return PLAN_PREMIUM

    monkeypatch.setattr(rate_limit_module, "resolve_plan_for_user", fake_resolve_plan)
    monkeypatch.setattr(
        generate_module,
        "_build_text_service",
        lambda session, current_user: _FakeTextService(),
    )

    app = FastAPI()
    _wire_auth(app, monkeypatch, user)
    app.dependency_overrides[rate_limit_module.get_rate_limiter] = fake_get_rate_limiter
    app.include_router(generate_module.router)

    async with await _client(app) as client:
        resp = await client.post(
            "/generate/text",
            headers={"X-Telegram-Init-Data": _build_init_data()},
            json={"prompt": "hello", "mode": MODE_BASIC},
        )

    assert resp.status_code == 200
    assert resp.json()["text"] == "ok"
    assert limiter.calls == [
        _ConsumedCall(plan=PLAN_PREMIUM, identifier=str(user.telegram_id), action="text")
    ]
