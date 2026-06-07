"""Endpoint-level tests for ``/api/v1/admin/content/*`` (issue #29).

Stubs the service layer so we can verify the FastAPI surface in
isolation: RBAC enforcement, payload validation, error mapping,
audit-log writes and request metadata propagation.

Mirrors the build-app pattern from ``test_admin_broadcasts_endpoints.py``
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


class FakeRow:
    """Common dynamic row used by stubbed service layer.

    The endpoint coerces these via ``Response.from_model(row)``; only the
    attributes accessed by the response model need to exist.
    """

    def __init__(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)


@dataclass
class _FakePage:
    items: list[Any]
    total: int
    page: int
    limit: int

    @property
    def has_more(self) -> bool:
        return (self.page * self.limit) < self.total


class FakeAuditLog:
    def __init__(
        self,
        *,
        admin_id: int,
        action: str,
        payload: dict[str, Any] | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        target_user_id: int | None = None,
    ) -> None:
        self.admin_id = admin_id
        self.target_user_id = target_user_id
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


def _make_prompt_row(state: dict[str, Any], *, admin_id: int, draft: Any) -> FakeRow:
    state["next_prompt_id"] += 1
    now = datetime.now(UTC)
    return FakeRow(
        id=state["next_prompt_id"],
        code=draft.code,
        title=draft.title,
        body=draft.body,
        category=draft.category,
        locale=draft.locale,
        sort_order=int(draft.sort_order or 0),
        is_active=bool(draft.is_active),
        created_by=admin_id,
        updated_by=admin_id,
        created_at=now,
        updated_at=now,
    )


def _make_faq_row(state: dict[str, Any], *, admin_id: int, draft: Any) -> FakeRow:
    state["next_faq_id"] += 1
    now = datetime.now(UTC)
    return FakeRow(
        id=state["next_faq_id"],
        question=draft.question,
        answer=draft.answer,
        category=draft.category,
        locale=draft.locale,
        sort_order=int(draft.sort_order or 0),
        is_active=bool(draft.is_active),
        created_by=admin_id,
        updated_by=admin_id,
        created_at=now,
        updated_at=now,
    )


def _make_welcome_row(state: dict[str, Any], *, admin_id: int, draft: Any) -> FakeRow:
    state["next_welcome_id"] += 1
    now = datetime.now(UTC)
    return FakeRow(
        id=state["next_welcome_id"],
        name=draft.name,
        body=draft.body,
        locale=draft.locale,
        is_active=bool(draft.is_active),
        created_by=admin_id,
        updated_by=admin_id,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def build_app(monkeypatch, admin_support, admin_analyst):
    """ASGI app with ``admin_content`` service hooks stubbed in memory."""
    from app.api.v1 import admin_content as router_module
    from app.auth.dependencies import _settings_dep, get_current_admin
    from app.core.database import get_session
    from app.main import create_app
    from app.services.admin_content import (
        ContentNotFoundError,
        DuplicateContentCodeError,
        InvalidContentPayloadError,
    )

    session = FakeSession()
    state: dict[str, Any] = {
        "prompts": {},
        "faqs": {},
        "welcomes": {},
        "audit_log": [],
        "next_prompt_id": 0,
        "next_faq_id": 0,
        "next_welcome_id": 0,
        "current_admin": admin_support,
        "session": session,
        "create_prompt_raise": None,
    }

    # ---------- prompt templates
    async def fake_list_prompts(_session, **kwargs):
        items = sorted(state["prompts"].values(), key=lambda r: r.id, reverse=True)
        return _FakePage(items=items, total=len(items), page=kwargs.get("page", 1), limit=kwargs.get("limit", 25))

    async def fake_get_prompt(_session, template_id):
        row = state["prompts"].get(template_id)
        if row is None:
            raise ContentNotFoundError("not found")
        return row

    async def fake_create_prompt(_session, *, admin, draft, ip_address=None, user_agent=None):
        if state["create_prompt_raise"] is not None:
            raise state["create_prompt_raise"]
        if draft.code == "duplicate":
            raise DuplicateContentCodeError("dup")
        if not draft.title.strip():
            raise InvalidContentPayloadError("title is required")
        row = _make_prompt_row(state, admin_id=admin.id, draft=draft)
        state["prompts"][row.id] = row
        state["audit_log"].append(
            FakeAuditLog(
                admin_id=admin.id,
                action="prompt_template.create",
                payload={"id": row.id, "code": row.code},
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )
        return row

    async def fake_update_prompt(_session, *, admin, template_id, draft, ip_address=None, user_agent=None):
        row = state["prompts"].get(template_id)
        if row is None:
            raise ContentNotFoundError("not found")
        if draft.code == "duplicate":
            raise DuplicateContentCodeError("dup")
        if not draft.title.strip():
            raise InvalidContentPayloadError("title is required")
        row.code = draft.code
        row.title = draft.title
        row.body = draft.body
        row.category = draft.category
        row.locale = draft.locale
        row.sort_order = int(draft.sort_order or 0)
        row.is_active = bool(draft.is_active)
        row.updated_by = admin.id
        row.updated_at = datetime.now(UTC)
        state["audit_log"].append(
            FakeAuditLog(
                admin_id=admin.id,
                action="prompt_template.update",
                payload={"id": row.id},
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )
        return row

    async def fake_delete_prompt(_session, *, admin, template_id, ip_address=None, user_agent=None):
        row = state["prompts"].get(template_id)
        if row is None:
            raise ContentNotFoundError("not found")
        del state["prompts"][template_id]
        state["audit_log"].append(
            FakeAuditLog(
                admin_id=admin.id,
                action="prompt_template.delete",
                payload={"id": template_id},
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

    # ---------- FAQs
    async def fake_list_faqs(_session, **kwargs):
        items = sorted(state["faqs"].values(), key=lambda r: r.id, reverse=True)
        return _FakePage(items=items, total=len(items), page=kwargs.get("page", 1), limit=kwargs.get("limit", 25))

    async def fake_get_faq(_session, faq_id):
        row = state["faqs"].get(faq_id)
        if row is None:
            raise ContentNotFoundError("not found")
        return row

    async def fake_create_faq(_session, *, admin, draft, ip_address=None, user_agent=None):
        if not draft.question.strip():
            raise InvalidContentPayloadError("question is required")
        row = _make_faq_row(state, admin_id=admin.id, draft=draft)
        state["faqs"][row.id] = row
        state["audit_log"].append(
            FakeAuditLog(
                admin_id=admin.id,
                action="faq_item.create",
                payload={"id": row.id},
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )
        return row

    async def fake_update_faq(_session, *, admin, faq_id, draft, ip_address=None, user_agent=None):
        row = state["faqs"].get(faq_id)
        if row is None:
            raise ContentNotFoundError("not found")
        row.question = draft.question
        row.answer = draft.answer
        row.category = draft.category
        row.locale = draft.locale
        row.sort_order = int(draft.sort_order or 0)
        row.is_active = bool(draft.is_active)
        row.updated_by = admin.id
        row.updated_at = datetime.now(UTC)
        state["audit_log"].append(
            FakeAuditLog(
                admin_id=admin.id,
                action="faq_item.update",
                payload={"id": row.id},
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )
        return row

    async def fake_delete_faq(_session, *, admin, faq_id, ip_address=None, user_agent=None):
        row = state["faqs"].get(faq_id)
        if row is None:
            raise ContentNotFoundError("not found")
        del state["faqs"][faq_id]
        state["audit_log"].append(
            FakeAuditLog(
                admin_id=admin.id,
                action="faq_item.delete",
                payload={"id": faq_id},
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

    # ---------- welcomes
    async def fake_list_welcomes(_session, **kwargs):
        items = sorted(state["welcomes"].values(), key=lambda r: r.id, reverse=True)
        return _FakePage(items=items, total=len(items), page=kwargs.get("page", 1), limit=kwargs.get("limit", 25))

    async def fake_get_welcome(_session, welcome_id):
        row = state["welcomes"].get(welcome_id)
        if row is None:
            raise ContentNotFoundError("not found")
        return row

    async def fake_create_welcome(_session, *, admin, draft, ip_address=None, user_agent=None):
        if not draft.name.strip():
            raise InvalidContentPayloadError("name is required")
        # mimic _deactivate_other_welcomes for the same locale
        if draft.is_active:
            for w in state["welcomes"].values():
                if w.locale == draft.locale:
                    w.is_active = False
        row = _make_welcome_row(state, admin_id=admin.id, draft=draft)
        state["welcomes"][row.id] = row
        state["audit_log"].append(
            FakeAuditLog(
                admin_id=admin.id,
                action="welcome_message.create",
                payload={"id": row.id},
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )
        return row

    async def fake_update_welcome(_session, *, admin, welcome_id, draft, ip_address=None, user_agent=None):
        row = state["welcomes"].get(welcome_id)
        if row is None:
            raise ContentNotFoundError("not found")
        if draft.is_active:
            for w in state["welcomes"].values():
                if w.id != row.id and w.locale == draft.locale:
                    w.is_active = False
        row.name = draft.name
        row.body = draft.body
        row.locale = draft.locale
        row.is_active = bool(draft.is_active)
        row.updated_by = admin.id
        row.updated_at = datetime.now(UTC)
        state["audit_log"].append(
            FakeAuditLog(
                admin_id=admin.id,
                action="welcome_message.update",
                payload={"id": row.id},
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )
        return row

    async def fake_delete_welcome(_session, *, admin, welcome_id, ip_address=None, user_agent=None):
        row = state["welcomes"].get(welcome_id)
        if row is None:
            raise ContentNotFoundError("not found")
        del state["welcomes"][welcome_id]
        state["audit_log"].append(
            FakeAuditLog(
                admin_id=admin.id,
                action="welcome_message.delete",
                payload={"id": welcome_id},
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

    # ---------- history
    async def fake_list_history(_session, *, entity=None, entity_id=None, page=1, limit=25):
        rows: list[Any] = []
        for ix, log in enumerate(state["audit_log"], start=1):
            if entity is not None and not log.action.startswith(f"{entity}."):
                continue
            if entity_id is not None:
                payload_id = (log.payload or {}).get("id")
                if payload_id != entity_id:
                    continue
            rows.append(
                FakeRow(
                    id=ix,
                    admin_id=log.admin_id,
                    target_user_id=log.target_user_id,
                    action=log.action,
                    payload=log.payload,
                    ip_address=log.ip_address,
                    user_agent=log.user_agent,
                    created_at=datetime.now(UTC),
                )
            )
        rows.sort(key=lambda r: r.id, reverse=True)
        return _FakePage(items=rows, total=len(rows), page=page, limit=limit)

    monkeypatch.setattr(router_module, "list_prompt_templates", fake_list_prompts)
    monkeypatch.setattr(router_module, "get_prompt_template", fake_get_prompt)
    monkeypatch.setattr(router_module, "create_prompt_template", fake_create_prompt)
    monkeypatch.setattr(router_module, "update_prompt_template", fake_update_prompt)
    monkeypatch.setattr(router_module, "delete_prompt_template", fake_delete_prompt)
    monkeypatch.setattr(router_module, "list_faq_items", fake_list_faqs)
    monkeypatch.setattr(router_module, "get_faq_item", fake_get_faq)
    monkeypatch.setattr(router_module, "create_faq_item", fake_create_faq)
    monkeypatch.setattr(router_module, "update_faq_item", fake_update_faq)
    monkeypatch.setattr(router_module, "delete_faq_item", fake_delete_faq)
    monkeypatch.setattr(router_module, "list_welcome_messages", fake_list_welcomes)
    monkeypatch.setattr(router_module, "get_welcome_message", fake_get_welcome)
    monkeypatch.setattr(router_module, "create_welcome_message", fake_create_welcome)
    monkeypatch.setattr(router_module, "update_welcome_message", fake_update_welcome)
    monkeypatch.setattr(router_module, "delete_welcome_message", fake_delete_welcome)
    monkeypatch.setattr(router_module, "list_content_history", fake_list_history)

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


def _prompt_body(**overrides: Any) -> dict[str, Any]:
    body = {
        "code": "greeting",
        "title": "Greeting",
        "body": "Hello {name}",
        "locale": "en",
        "sort_order": 0,
        "is_active": True,
    }
    body.update(overrides)
    return body


def _faq_body(**overrides: Any) -> dict[str, Any]:
    body = {
        "question": "How do I pay?",
        "answer": "Use the /pay command.",
        "locale": "en",
        "sort_order": 0,
        "is_active": True,
    }
    body.update(overrides)
    return body


def _welcome_body(**overrides: Any) -> dict[str, Any]:
    body = {
        "name": "Default",
        "body": "Welcome aboard!",
        "locale": "en",
        "is_active": False,
    }
    body.update(overrides)
    return body


# ---------------------------------------------------------------- prompt templates


@pytest.mark.asyncio
async def test_create_prompt_template_persists_and_audits(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        resp = await c.post(
            "/api/v1/admin/content/prompt-templates",
            json=_prompt_body(),
            headers={"X-Forwarded-For": "203.0.113.7", "User-Agent": "tests/1.0"},
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["code"] == "greeting"
    assert body["created_by"] == 1
    audit = build_app["audit_log"][-1]
    assert audit.action == "prompt_template.create"
    assert audit.ip_address == "127.0.0.1"
    assert audit.user_agent == "tests/1.0"
    assert build_app["session"].committed is True


@pytest.mark.asyncio
async def test_create_prompt_rejects_duplicate_code(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        resp = await c.post(
            "/api/v1/admin/content/prompt-templates",
            json=_prompt_body(code="duplicate"),
        )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "duplicate_code"


@pytest.mark.asyncio
async def test_create_prompt_forbidden_for_analyst(build_app, admin_analyst) -> None:
    build_app["current_admin"] = admin_analyst
    async with await _client(build_app["app"]) as c:
        resp = await c.post(
            "/api/v1/admin/content/prompt-templates",
            json=_prompt_body(),
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_prompt_templates_returns_page(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        for ix in range(3):
            await c.post(
                "/api/v1/admin/content/prompt-templates",
                json=_prompt_body(code=f"greet_{ix}"),
            )
        resp = await c.get("/api/v1/admin/content/prompt-templates?page=1&limit=25")
    body = resp.json()
    assert resp.status_code == 200
    assert body["total"] == 3
    assert body["has_more"] is False


@pytest.mark.asyncio
async def test_get_prompt_template_404(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        resp = await c.get("/api/v1/admin/content/prompt-templates/999")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "prompt_template_not_found"


@pytest.mark.asyncio
async def test_update_prompt_template_updates_and_audits(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        await c.post(
            "/api/v1/admin/content/prompt-templates",
            json=_prompt_body(),
        )
        resp = await c.put(
            "/api/v1/admin/content/prompt-templates/1",
            json=_prompt_body(title="Updated title"),
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["title"] == "Updated title"
    actions = [a.action for a in build_app["audit_log"]]
    assert "prompt_template.update" in actions


@pytest.mark.asyncio
async def test_update_prompt_404(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        resp = await c.put(
            "/api/v1/admin/content/prompt-templates/999",
            json=_prompt_body(),
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_prompt_template_audits(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        await c.post(
            "/api/v1/admin/content/prompt-templates",
            json=_prompt_body(),
        )
        resp = await c.delete("/api/v1/admin/content/prompt-templates/1")
    assert resp.status_code == 204
    assert build_app["audit_log"][-1].action == "prompt_template.delete"
    assert 1 not in build_app["prompts"]


@pytest.mark.asyncio
async def test_delete_prompt_404(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        resp = await c.delete("/api/v1/admin/content/prompt-templates/999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_analyst_can_read_but_not_mutate(build_app, admin_analyst) -> None:
    # support admin seeds a row first
    async with await _client(build_app["app"]) as c:
        await c.post("/api/v1/admin/content/prompt-templates", json=_prompt_body())
    build_app["current_admin"] = admin_analyst
    async with await _client(build_app["app"]) as c:
        get_resp = await c.get("/api/v1/admin/content/prompt-templates")
        del_resp = await c.delete("/api/v1/admin/content/prompt-templates/1")
    assert get_resp.status_code == 200
    assert del_resp.status_code == 403


# ---------------------------------------------------------------- FAQs


@pytest.mark.asyncio
async def test_create_faq_persists_and_audits(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        resp = await c.post("/api/v1/admin/content/faqs", json=_faq_body())
    assert resp.status_code == 201, resp.text
    assert resp.json()["question"] == "How do I pay?"
    assert build_app["audit_log"][-1].action == "faq_item.create"


@pytest.mark.asyncio
async def test_update_faq_404(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        resp = await c.put(
            "/api/v1/admin/content/faqs/999",
            json=_faq_body(),
        )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "faq_not_found"


@pytest.mark.asyncio
async def test_delete_faq_audits(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        await c.post("/api/v1/admin/content/faqs", json=_faq_body())
        resp = await c.delete("/api/v1/admin/content/faqs/1")
    assert resp.status_code == 204
    assert build_app["audit_log"][-1].action == "faq_item.delete"


@pytest.mark.asyncio
async def test_faqs_forbidden_for_analyst(build_app, admin_analyst) -> None:
    build_app["current_admin"] = admin_analyst
    async with await _client(build_app["app"]) as c:
        resp = await c.post("/api/v1/admin/content/faqs", json=_faq_body())
    assert resp.status_code == 403


# ---------------------------------------------------------------- welcomes


@pytest.mark.asyncio
async def test_create_welcome_persists_and_audits(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        resp = await c.post(
            "/api/v1/admin/content/welcomes",
            json=_welcome_body(),
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "Default"
    assert body["is_active"] is False
    assert build_app["audit_log"][-1].action == "welcome_message.create"


@pytest.mark.asyncio
async def test_create_welcome_deactivates_siblings_in_same_locale(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        # first welcome is active
        await c.post(
            "/api/v1/admin/content/welcomes",
            json=_welcome_body(name="Old", is_active=True),
        )
        # second active welcome in same locale should deactivate the first
        await c.post(
            "/api/v1/admin/content/welcomes",
            json=_welcome_body(name="New", is_active=True),
        )
    welcomes = list(build_app["welcomes"].values())
    actives = [w for w in welcomes if w.is_active]
    assert len(actives) == 1
    assert actives[0].name == "New"


@pytest.mark.asyncio
async def test_update_welcome_404(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        resp = await c.put(
            "/api/v1/admin/content/welcomes/999",
            json=_welcome_body(),
        )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "welcome_not_found"


@pytest.mark.asyncio
async def test_welcomes_forbidden_for_analyst(build_app, admin_analyst) -> None:
    build_app["current_admin"] = admin_analyst
    async with await _client(build_app["app"]) as c:
        resp = await c.post(
            "/api/v1/admin/content/welcomes",
            json=_welcome_body(),
        )
    assert resp.status_code == 403


# ---------------------------------------------------------------- history


@pytest.mark.asyncio
async def test_history_returns_all_content_actions(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        await c.post("/api/v1/admin/content/prompt-templates", json=_prompt_body())
        await c.post("/api/v1/admin/content/faqs", json=_faq_body())
        await c.post("/api/v1/admin/content/welcomes", json=_welcome_body())
        resp = await c.get("/api/v1/admin/content/history?limit=50")
    body = resp.json()
    assert resp.status_code == 200, resp.text
    actions = {item["action"] for item in body["items"]}
    assert {"prompt_template.create", "faq_item.create", "welcome_message.create"} <= actions


@pytest.mark.asyncio
async def test_history_filters_by_entity(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        await c.post("/api/v1/admin/content/prompt-templates", json=_prompt_body())
        await c.post("/api/v1/admin/content/faqs", json=_faq_body())
        resp = await c.get("/api/v1/admin/content/history?entity=faq_item")
    body = resp.json()
    assert resp.status_code == 200
    assert all(item["action"].startswith("faq_item.") for item in body["items"])
    assert body["total"] >= 1


@pytest.mark.asyncio
async def test_history_filters_by_entity_id(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        await c.post("/api/v1/admin/content/prompt-templates", json=_prompt_body(code="a"))
        await c.post("/api/v1/admin/content/prompt-templates", json=_prompt_body(code="b"))
        resp = await c.get(
            "/api/v1/admin/content/history?entity=prompt_template&entity_id=2"
        )
    body = resp.json()
    assert resp.status_code == 200
    assert body["total"] == 1
    assert (body["items"][0]["payload"] or {}).get("id") == 2


@pytest.mark.asyncio
async def test_history_rejects_invalid_entity(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        resp = await c.get("/api/v1/admin/content/history?entity=bogus")
    # Pydantic Literal rejects bad enum at validation time → 422
    assert resp.status_code == 422
