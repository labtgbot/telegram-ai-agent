"""Endpoint-level tests for ``/api/v1/admin/broadcasts/*`` (issue #28).

Stubs the service layer so we can verify the FastAPI surface in
isolation: RBAC enforcement, payload validation, error mapping,
audit log writes and request metadata propagation.

Mirrors the build-app pattern from ``test_admin_users_endpoints.py``
to keep the suite fast and PostgreSQL-free.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

JWT_SECRET = "test-secret"


class _Settings:
    app_env = "development"
    app_debug = True
    telegram_bot_token = "1:TEST-AAA"
    telegram_init_data_max_age = 600
    admin_jwt_secret = JWT_SECRET
    admin_jwt_algorithm = "HS256"
    admin_access_token_ttl = 60
    admin_refresh_token_ttl = 600
    admin_login_code_ttl = 60
    admin_login_code_length = 6
    admin_login_max_attempts = 5
    admin_super_telegram_ids = ""

    @property
    def is_development(self) -> bool:
        return True

    @property
    def super_admin_ids(self) -> set[int]:
        return set()


class FakeUser:
    def __init__(self, *, id: int, telegram_id: int, role: str = "user") -> None:
        self.id = id
        self.telegram_id = telegram_id
        self.role = role
        self.username = f"u{telegram_id}"
        self.is_premium = False
        self.is_banned = False


class FakeBroadcast:
    """In-memory broadcast row used by the stubbed service layer."""

    def __init__(
        self,
        *,
        id: int,
        created_by: int,
        text: str = "hello",
        title: str | None = None,
        parse_mode: str | None = "HTML",
        media_type: str | None = None,
        media_url: str | None = None,
        buttons: list[dict[str, Any]] | None = None,
        audience: str = "all",
        audience_filter: dict[str, Any] | None = None,
        status: str = "draft",
        scheduled_at: datetime | None = None,
        total_recipients: int = 0,
    ) -> None:
        self.id = id
        self.created_by = created_by
        self.text = text
        self.title = title
        self.parse_mode = parse_mode
        self.media_type = media_type
        self.media_url = media_url
        self.buttons = buttons
        self.audience = audience
        self.audience_filter = audience_filter
        self.status = status
        self.scheduled_at = scheduled_at
        self.started_at: datetime | None = None
        self.finished_at: datetime | None = None
        self.cancelled_at: datetime | None = None
        self.total_recipients = total_recipients
        self.sent_count = 0
        self.delivered_count = 0
        self.failed_count = 0
        self.skipped_count = 0
        self.clicks_count = 0
        self.last_error: str | None = None
        now = datetime.now(UTC)
        self.created_at = now
        self.updated_at = now


@dataclass
class _FakeListPage:
    items: list[FakeBroadcast]
    total: int
    page: int
    limit: int

    @property
    def has_more(self) -> bool:
        return (self.page * self.limit) < self.total


@dataclass
class _FakeStats:
    broadcast: FakeBroadcast
    total_recipients: int
    pending: int
    sent: int
    delivered: int
    failed: int
    skipped: int
    clicks: int


class FakeAuditLog:
    def __init__(
        self,
        *,
        admin_id: int,
        action: str,
        payload: dict[str, Any] | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        self.admin_id = admin_id
        self.action = action
        self.payload = payload
        self.ip_address = ip_address
        self.user_agent = user_agent


class FakeSession:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


@pytest.fixture
def admin_support() -> FakeUser:
    return FakeUser(id=1, telegram_id=100, role="support_admin")


@pytest.fixture
def admin_analyst() -> FakeUser:
    return FakeUser(id=2, telegram_id=200, role="analyst")


@pytest.fixture
def build_app(monkeypatch, admin_support, admin_analyst):
    """ASGI app with ``admin_broadcasts`` service hooks stubbed in memory."""
    from app.api.v1 import admin_broadcasts as router_module
    from app.auth.dependencies import _settings_dep, get_current_admin
    from app.core.database import get_session
    from app.main import create_app
    from app.services.broadcast import (
        BroadcastNotCancellableError,
        BroadcastNotFoundError,
        EmptyAudienceError,
        InvalidAudienceError,
        InvalidBroadcastPayloadError,
    )

    session = FakeSession()
    state: dict[str, Any] = {
        "broadcasts": {},
        "next_id": 0,
        "audit_log": [],
        "current_admin": admin_support,
        "session": session,
        # Hook points for individual tests to override:
        "preview_total": 42,
        "preview_raise": None,
        "create_raise": None,
    }

    async def fake_preview_audience(_session, *, audience, audience_filter=None):
        if state["preview_raise"] is not None:
            raise state["preview_raise"]
        if audience == "rocket-launch":
            raise InvalidAudienceError(f"unsupported audience={audience!r}")
        return int(state["preview_total"])

    async def fake_create_broadcast(
        _session,
        *,
        admin,
        draft,
        ip_address=None,
        user_agent=None,
    ):
        if state["create_raise"] is not None:
            raise state["create_raise"]
        if draft.audience == "rocket-launch":
            raise InvalidAudienceError("unsupported audience")
        if not draft.text or not draft.text.strip():
            raise InvalidBroadcastPayloadError("text is required")
        if draft.audience == "custom" and not draft.audience_filter:
            raise EmptyAudienceError("audience matched zero users")

        state["next_id"] += 1
        b = FakeBroadcast(
            id=state["next_id"],
            created_by=admin.id,
            text=draft.text,
            title=draft.title,
            parse_mode=draft.parse_mode,
            media_type=draft.media_type,
            media_url=draft.media_url,
            buttons=[btn.to_dict() for btn in draft.buttons] or None,
            audience=draft.audience,
            audience_filter=draft.audience_filter,
            status=(
                "scheduled"
                if draft.scheduled_at and draft.scheduled_at > datetime.now(UTC)
                else "draft"
            ),
            scheduled_at=draft.scheduled_at,
            total_recipients=3,
        )
        state["broadcasts"][b.id] = b
        state["audit_log"].append(
            FakeAuditLog(
                admin_id=admin.id,
                action="broadcast.create",
                payload={
                    "broadcast_id": b.id,
                    "audience": b.audience,
                    "total_recipients": b.total_recipients,
                },
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )
        return b

    async def fake_cancel_broadcast(
        _session,
        *,
        admin,
        broadcast_id,
        ip_address=None,
        user_agent=None,
    ):
        b = state["broadcasts"].get(broadcast_id)
        if b is None:
            raise BroadcastNotFoundError("not found")
        if b.status not in ("draft", "scheduled", "in_progress"):
            raise BroadcastNotCancellableError(
                f"broadcast in status={b.status!r} cannot be cancelled"
            )
        b.status = "cancelled"
        b.cancelled_at = datetime.now(UTC)
        b.finished_at = b.cancelled_at
        state["audit_log"].append(
            FakeAuditLog(
                admin_id=admin.id,
                action="broadcast.cancel",
                payload={"broadcast_id": b.id},
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )
        return b

    async def fake_get_broadcast(_session, broadcast_id):
        b = state["broadcasts"].get(broadcast_id)
        if b is None:
            raise BroadcastNotFoundError("not found")
        return b

    async def fake_list_broadcasts(_session, *, status=None, page=1, limit=25):
        items = list(state["broadcasts"].values())
        if status:
            items = [b for b in items if b.status == status]
        items.sort(key=lambda b: b.id, reverse=True)
        total = len(items)
        items = items[(page - 1) * limit : page * limit]
        return _FakeListPage(items=items, total=total, page=page, limit=limit)

    async def fake_get_broadcast_stats(_session, broadcast_id):
        b = state["broadcasts"].get(broadcast_id)
        if b is None:
            raise BroadcastNotFoundError("not found")
        return _FakeStats(
            broadcast=b,
            total_recipients=b.total_recipients,
            pending=b.total_recipients,
            sent=0,
            delivered=0,
            failed=0,
            skipped=0,
            clicks=0,
        )

    monkeypatch.setattr(router_module, "preview_audience", fake_preview_audience)
    monkeypatch.setattr(router_module, "create_broadcast", fake_create_broadcast)
    monkeypatch.setattr(router_module, "cancel_broadcast", fake_cancel_broadcast)
    monkeypatch.setattr(router_module, "get_broadcast", fake_get_broadcast)
    monkeypatch.setattr(router_module, "list_broadcasts", fake_list_broadcasts)
    monkeypatch.setattr(router_module, "get_broadcast_stats", fake_get_broadcast_stats)

    app = create_app()

    async def _yield_session():
        yield session

    async def _yield_admin():
        return state["current_admin"]

    app.dependency_overrides[get_session] = _yield_session
    app.dependency_overrides[_settings_dep] = lambda: _Settings()
    app.dependency_overrides[get_current_admin] = _yield_admin

    state["app"] = app
    return state


async def _client(app: Any) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------- preview


@pytest.mark.asyncio
async def test_preview_audience_returns_count(build_app) -> None:
    build_app["preview_total"] = 17
    async with await _client(build_app["app"]) as c:
        resp = await c.post(
            "/api/v1/admin/broadcasts/preview-audience",
            json={"audience": "premium"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"audience": "premium", "total": 17}


@pytest.mark.asyncio
async def test_preview_audience_rejects_unknown_audience(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        resp = await c.post(
            "/api/v1/admin/broadcasts/preview-audience",
            json={"audience": "rocket-launch"},
        )
    assert resp.status_code == 400
    assert "unsupported" in resp.json()["detail"]


# ---------------------------------------------------------------- create


@pytest.mark.asyncio
async def test_create_broadcast_persists_and_audits(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        resp = await c.post(
            "/api/v1/admin/broadcasts",
            json={
                "text": "<b>Sale!</b>",
                "title": "Spring",
                "parse_mode": "HTML",
                "audience": "all",
                "buttons": [{"text": "Open", "url": "https://example.com"}],
            },
            headers={
                "X-Forwarded-For": "203.0.113.7, 10.0.0.1",
                "User-Agent": "tests/1.0",
            },
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["audience"] == "all"
    assert body["title"] == "Spring"
    assert body["buttons"] == [{"text": "Open", "url": "https://example.com"}]
    assert body["status"] == "draft"
    assert body["total_recipients"] == 3

    audit = build_app["audit_log"][-1]
    assert audit.action == "broadcast.create"
    assert audit.ip_address == "127.0.0.1"
    assert audit.user_agent == "tests/1.0"
    assert build_app["session"].committed is True


@pytest.mark.asyncio
async def test_create_broadcast_maps_empty_audience_to_400(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        resp = await c.post(
            "/api/v1/admin/broadcasts",
            json={"text": "hi", "audience": "custom"},
        )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "empty_audience"


@pytest.mark.asyncio
async def test_create_broadcast_maps_invalid_audience_to_400(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        resp = await c.post(
            "/api/v1/admin/broadcasts",
            json={"text": "hi", "audience": "rocket-launch"},
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_create_broadcast_requires_text(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        resp = await c.post(
            "/api/v1/admin/broadcasts",
            json={"text": "", "audience": "all"},
        )
    # Pydantic min_length=1 catches this at validation time
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_broadcast_forbidden_for_analyst(build_app) -> None:
    build_app["current_admin"] = FakeUser(id=2, telegram_id=200, role="analyst")
    async with await _client(build_app["app"]) as c:
        resp = await c.post(
            "/api/v1/admin/broadcasts",
            json={"text": "hi", "audience": "all"},
        )
    assert resp.status_code == 403


# ---------------------------------------------------------------- list / get / stats


@pytest.mark.asyncio
async def test_list_broadcasts_returns_page(build_app) -> None:
    # seed three broadcasts via the create endpoint
    async with await _client(build_app["app"]) as c:
        for i in range(3):
            await c.post(
                "/api/v1/admin/broadcasts",
                json={"text": f"msg {i}", "audience": "all"},
            )
        resp = await c.get("/api/v1/admin/broadcasts?page=1&limit=25")
    body = resp.json()
    assert resp.status_code == 200, resp.text
    assert body["total"] == 3
    assert body["page"] == 1
    assert body["limit"] == 25
    assert body["has_more"] is False
    assert len(body["items"]) == 3


@pytest.mark.asyncio
async def test_list_broadcasts_filters_by_status(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        await c.post(
            "/api/v1/admin/broadcasts",
            json={"text": "x", "audience": "all"},
        )
        # cancel it so we have a known status
        await c.post("/api/v1/admin/broadcasts/1/cancel")
        resp = await c.get("/api/v1/admin/broadcasts?status=cancelled")
    body = resp.json()
    assert resp.status_code == 200
    assert body["total"] == 1
    assert body["items"][0]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_get_broadcast_returns_payload(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        await c.post(
            "/api/v1/admin/broadcasts",
            json={"text": "hi", "audience": "all"},
        )
        resp = await c.get("/api/v1/admin/broadcasts/1")
    body = resp.json()
    assert resp.status_code == 200
    assert body["id"] == 1


@pytest.mark.asyncio
async def test_get_broadcast_404(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        resp = await c.get("/api/v1/admin/broadcasts/999")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "broadcast_not_found"


@pytest.mark.asyncio
async def test_get_broadcast_stats_returns_breakdown(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        await c.post(
            "/api/v1/admin/broadcasts",
            json={"text": "hi", "audience": "all"},
        )
        resp = await c.get("/api/v1/admin/broadcasts/1/stats")
    body = resp.json()
    assert resp.status_code == 200
    assert body["broadcast"]["id"] == 1
    assert body["total_recipients"] == 3
    assert body["pending"] == 3
    assert body["delivered"] == 0


@pytest.mark.asyncio
async def test_list_audiences_returns_known_selectors(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        resp = await c.get("/api/v1/admin/broadcasts/audiences")
    assert resp.status_code == 200
    audiences = resp.json()["audiences"]
    assert "all" in audiences
    assert "custom" in audiences


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        ("POST", "/api/v1/admin/broadcasts/preview-audience", {"audience": "premium"}),
        ("GET", "/api/v1/admin/broadcasts", None),
        ("GET", "/api/v1/admin/broadcasts/audiences", None),
        ("GET", "/api/v1/admin/broadcasts/1", None),
        ("GET", "/api/v1/admin/broadcasts/1/stats", None),
    ],
)
async def test_broadcast_reads_forbidden_for_analyst(
    build_app,
    admin_analyst,
    method,
    path,
    json_body,
) -> None:
    async with await _client(build_app["app"]) as c:
        await c.post(
            "/api/v1/admin/broadcasts",
            json={"text": "seed", "audience": "all"},
        )
    build_app["current_admin"] = admin_analyst
    async with await _client(build_app["app"]) as c:
        resp = await c.request(method, path, json=json_body)
    assert resp.status_code == 403


# ---------------------------------------------------------------- cancel


@pytest.mark.asyncio
async def test_cancel_broadcast_marks_cancelled_and_audits(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        await c.post(
            "/api/v1/admin/broadcasts",
            json={"text": "hi", "audience": "all"},
        )
        resp = await c.post(
            "/api/v1/admin/broadcasts/1/cancel",
            headers={"X-Forwarded-For": "1.1.1.1"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "cancelled"
    audit = build_app["audit_log"][-1]
    assert audit.action == "broadcast.cancel"
    assert audit.ip_address == "127.0.0.1"


@pytest.mark.asyncio
async def test_cancel_broadcast_404_when_missing(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        resp = await c.post("/api/v1/admin/broadcasts/9999/cancel")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "broadcast_not_found"


@pytest.mark.asyncio
async def test_cancel_broadcast_409_when_completed(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        await c.post(
            "/api/v1/admin/broadcasts",
            json={"text": "hi", "audience": "all"},
        )
    build_app["broadcasts"][1].status = "completed"
    async with await _client(build_app["app"]) as c:
        resp = await c.post("/api/v1/admin/broadcasts/1/cancel")
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_cancel_broadcast_forbidden_for_analyst(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        await c.post(
            "/api/v1/admin/broadcasts",
            json={"text": "hi", "audience": "all"},
        )
    build_app["current_admin"] = FakeUser(id=2, telegram_id=200, role="analyst")
    async with await _client(build_app["app"]) as c:
        resp = await c.post("/api/v1/admin/broadcasts/1/cancel")
    assert resp.status_code == 403
