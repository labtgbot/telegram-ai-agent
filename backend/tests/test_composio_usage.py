"""Database-backed test for ``log_invocation`` (Composio audit row).

Uses the same ``db_session`` fixture as the token-service tests and
skips automatically when ``DATABASE_URL`` is not configured.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import User
from app.models.token_usage_log import TokenUsageLog
from app.services.composio import ToolResult, log_invocation


async def _make_user(session, *, telegram_id: int, code: str) -> User:
    user = User(
        telegram_id=telegram_id,
        username=f"u{telegram_id}",
        referral_code=code,
        token_balance=0,
    )
    session.add(user)
    await session.flush()
    return user


@pytest.mark.asyncio
async def test_log_invocation_writes_token_usage_row(db_session):
    user = await _make_user(db_session, telegram_id=9_100_001, code="CMP-LOG-1")
    result = ToolResult(
        tool="gemini",
        successful=True,
        data={"text": "hi"},
        attempts=1,
        latency_ms=42,
        service_type="text",
        mcp_server="composio-prod-1",
    )

    entry = await log_invocation(
        db_session,
        user_id=user.id,
        result=result,
        tokens_consumed=0,
        request_params={"prompt": "hi"},
    )

    assert entry.id > 0
    fetched = (
        await db_session.execute(select(TokenUsageLog).where(TokenUsageLog.id == entry.id))
    ).scalar_one()
    assert fetched.user_id == user.id
    assert fetched.service_type == "text"
    assert fetched.composio_tool == "gemini"
    assert fetched.mcp_server == "composio-prod-1"
    assert fetched.processing_time_ms == 42
    assert fetched.response_status == "ok"
    assert fetched.tokens_consumed == 0
    assert fetched.request_params == {"prompt": "hi"}


@pytest.mark.asyncio
async def test_log_invocation_records_error_status(db_session):
    user = await _make_user(db_session, telegram_id=9_100_002, code="CMP-LOG-2")
    result = ToolResult(
        tool="image_gen",
        successful=False,
        error="upstream timeout",
        attempts=3,
        latency_ms=1500,
        service_type="image",
    )
    entry = await log_invocation(db_session, user_id=user.id, result=result)
    fetched = (
        await db_session.execute(select(TokenUsageLog).where(TokenUsageLog.id == entry.id))
    ).scalar_one()
    assert fetched.response_status == "error"
    assert fetched.composio_tool == "image_gen"
    assert fetched.service_type == "image"
