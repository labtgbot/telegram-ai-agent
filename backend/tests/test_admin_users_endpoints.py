"""Endpoint-level tests for ``/api/v1/admin/users/*`` (issue #25).

Stubs every DB and service surface in memory so the suite stays fast and
runs without PostgreSQL.  The intent is to verify the FastAPI wiring:
RBAC enforcement, parameter validation, error-mapping, audit log writes
and the bot-message delivery branches.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

JWT_SECRET = "test-secret"


# ---------------------------------------------------------------- fixtures


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
    def __init__(
        self,
        *,
        id: int,
        telegram_id: int,
        role: str = "user",
        is_premium: bool = False,
        is_banned: bool = False,
        username: str | None = None,
        first_name: str | None = None,
        token_balance: int = 0,
    ) -> None:
        self.id = id
        self.telegram_id = telegram_id
        self.username = username or f"u{telegram_id}"
        self.first_name = first_name or "First"
        self.last_name = "Last"
        self.language_code = "en"
        self.role = role
        self.is_premium = is_premium
        self.is_banned = is_banned
        self.ban_reason: str | None = None
        self.banned_until: datetime | None = None
        self.token_balance = token_balance
        self.total_tokens_purchased = 0
        self.total_tokens_spent = 0
        self.total_requests = 0
        self.referral_code = f"REF-{telegram_id}"
        self.referred_by: int | None = None
        self.created_at = datetime.now(UTC)
        self.last_active_at: datetime | None = datetime.now(UTC)
        self.last_login_at: datetime | None = None


class FakeAuditLog:
    """Minimal stand-in for the AdminAuditLog ORM row."""

    def __init__(
        self,
        *,
        admin_id: int,
        target_user_id: int | None,
        action: str,
        payload: dict[str, Any] | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        self.id = 0
        self.admin_id = admin_id
        self.target_user_id = target_user_id
        self.action = action
        self.payload = payload
        self.ip_address = ip_address
        self.user_agent = user_agent
        self.created_at = datetime.now(UTC)


class _FakePage:
    """Mimics :class:`UserListPage` / :class:`AuditLogPage` without dataclass."""

    def __init__(
        self,
        items: list[Any],
        *,
        total: int,
        page: int,
        limit: int,
    ) -> None:
        self.items = items
        self.total = total
        self.page = page
        self.limit = limit
        self.has_more = (page * limit) < total


class _FakeStats:
    def __init__(self, user: FakeUser) -> None:
        self.user = user
        self.transactions_total = 0
        self.recent_transactions: list[Any] = []
        self.services_usage: list[Any] = []
        self.referrals_count = 0
        self.recent_referrals: list[Any] = []


class FakeSession:
    """Bare-bones async session: we override every code path that hits it."""

    def __init__(self, users: dict[int, FakeUser]) -> None:
        self.users = users
        self.committed = False
        self.rolled_back = False

    async def get(self, model, key):  # noqa: ANN001
        return self.users.get(int(key))

    async def flush(self) -> None:  # pragma: no cover - never reached in tests
        return None

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True

    async def execute(self, *_a, **_kw):  # pragma: no cover - service stubbed
        raise AssertionError("session.execute should be stubbed by tests")


class FakeBotClient:
    def __init__(self, *, fail: bool = False, fail_description: str = "boom") -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail = fail
        self.fail_description = fail_description

    async def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        parse_mode: str | None = "HTML",
        disable_web_page_preview: bool | None = True,
    ) -> Any:
        from app.bot.client import TelegramApiError

        self.calls.append(
            {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": disable_web_page_preview,
            }
        )
        if self.fail:
            raise TelegramApiError(
                "sendMessage", self.fail_description, error_code=400
            )
        return {"message_id": 777, "chat": {"id": chat_id}}


@pytest.fixture
def admin_super() -> FakeUser:
    return FakeUser(
        id=1, telegram_id=100, role="super_admin", username="boss"
    )


@pytest.fixture
def admin_analyst() -> FakeUser:
    return FakeUser(
        id=2, telegram_id=200, role="analyst", username="seer"
    )


@pytest.fixture
def target_user() -> FakeUser:
    return FakeUser(
        id=10, telegram_id=1000, role="user", username="bob", token_balance=100
    )


@pytest.fixture
def fake_bot() -> FakeBotClient:
    return FakeBotClient()


@pytest.fixture
def build_app(monkeypatch, admin_super, admin_analyst, target_user, fake_bot):
    """Compose an ASGI app with the admin-users router fully stubbed."""
    from app.api.v1 import admin_users as router_module
    from app.api.v1 import bot as bot_module
    from app.auth.dependencies import _settings_dep, get_current_admin
    from app.core.database import get_session
    from app.main import create_app

    users: dict[int, FakeUser] = {
        admin_super.id: admin_super,
        admin_analyst.id: admin_analyst,
        target_user.id: target_user,
    }
    audit_log: list[FakeAuditLog] = []
    session = FakeSession(users)
    current_admin: dict[str, FakeUser] = {"user": admin_super}

    async def fake_list_users(_session, **kwargs):  # noqa: ANN001
        from app.services.admin_users import (
            ALLOWED_SORT_FIELDS,
            InvalidFilterError,
        )

        sort_field = kwargs.get("sort", "created_at")
        direction = kwargs.get("direction", "desc")
        if sort_field not in ALLOWED_SORT_FIELDS:
            raise InvalidFilterError(f"unsupported sort field: {sort_field}")
        if direction not in ("asc", "desc"):
            raise InvalidFilterError(f"unsupported sort direction: {direction}")

        items = list(users.values())
        # respect search by username prefix for one assertion case
        filters = kwargs.get("filters")
        if filters and filters.search:
            needle = filters.search.lower().lstrip("@")
            items = [u for u in items if needle in (u.username or "").lower()]
        if filters and filters.is_premium is not None:
            items = [u for u in items if bool(u.is_premium) is filters.is_premium]
        if filters and filters.is_banned is not None:
            items = [u for u in items if bool(u.is_banned) is filters.is_banned]
        page = int(kwargs.get("page") or 1)
        limit = int(kwargs.get("limit") or 25)
        total = len(items)
        items = items[(page - 1) * limit : page * limit]
        return _FakePage(items=items, total=total, page=page, limit=limit)

    async def fake_get_user_stats(_session, user_id: int):  # noqa: ANN001
        from app.services.admin_users import UserNotFoundError

        user = users.get(user_id)
        if user is None:
            raise UserNotFoundError(f"user {user_id} not found")
        return _FakeStats(user)

    async def fake_ban_user(
        _session,
        *,
        admin,
        user_id,
        reason=None,
        banned_until=None,
        ip_address=None,
        user_agent=None,
    ):
        from app.auth.rbac import Role
        from app.services.admin_users import (
            CannotTargetAdminError,
            CannotTargetSelfError,
            UserNotFoundError,
        )

        if user_id == admin.id:
            raise CannotTargetSelfError("cannot ban self")
        target = users.get(user_id)
        if target is None:
            raise UserNotFoundError(f"user {user_id} not found")
        actual_role = Role.coerce(target.role)
        if actual_role in (Role.SUPPORT_ADMIN, Role.SUPER_ADMIN):
            raise CannotTargetAdminError("cannot ban admin")
        target.is_banned = True
        target.ban_reason = reason
        target.banned_until = banned_until
        audit_log.append(
            FakeAuditLog(
                admin_id=admin.id,
                target_user_id=target.id,
                action="user.ban",
                payload={"reason": reason},
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )
        return target

    async def fake_unban_user(
        _session,
        *,
        admin,
        user_id,
        ip_address=None,
        user_agent=None,
    ):
        from app.services.admin_users import UserNotFoundError

        target = users.get(user_id)
        if target is None:
            raise UserNotFoundError(f"user {user_id} not found")
        target.is_banned = False
        target.ban_reason = None
        target.banned_until = None
        audit_log.append(
            FakeAuditLog(
                admin_id=admin.id,
                target_user_id=target.id,
                action="user.unban",
                payload=None,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )
        return target

    async def fake_record_audit_event(
        _session,
        *,
        admin,
        target_user_id,
        action,
        payload,
        ip_address=None,
        user_agent=None,
    ):
        log = FakeAuditLog(
            admin_id=admin.id,
            target_user_id=target_user_id,
            action=action,
            payload=payload,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        audit_log.append(log)
        return log

    async def fake_list_audit_log(
        _session,
        *,
        admin_id=None,
        target_user_id=None,
        action=None,
        page=1,
        limit=25,
    ):
        items = list(audit_log)
        if admin_id is not None:
            items = [r for r in items if r.admin_id == admin_id]
        if target_user_id is not None:
            items = [r for r in items if r.target_user_id == target_user_id]
        if action:
            items = [r for r in items if r.action == action]
        total = len(items)
        items = items[(page - 1) * limit : page * limit]
        return _FakePage(items=items, total=total, page=page, limit=limit)

    async def fake_export_users_csv(_session, *, filters=None, limit=50_000):  # noqa: ANN001
        items = list(users.values())
        if filters and filters.is_banned is not None:
            items = [u for u in items if bool(u.is_banned) is filters.is_banned]
        header = "id,telegram_id,username\n"
        body = "".join(f"{u.id},{u.telegram_id},{u.username}\n" for u in items)
        return header + body

    class _FakeTokenService:
        def __init__(self, _session, balance_cache=None):
            pass

        async def manual_bonus(
            self, *, user_id: int, amount: int, reason: str, admin_id: int
        ):
            from app.services.token_service import (
                InvalidAmountError,
                TokenOperationResult,
                UserNotFoundError,
            )

            target = users.get(user_id)
            if target is None:
                raise UserNotFoundError(f"user {user_id}")
            if amount <= 0:
                raise InvalidAmountError("must be positive")
            target.token_balance += amount
            target.total_tokens_purchased += amount
            return TokenOperationResult(
                user_id=target.id,
                amount=amount,
                new_balance=target.token_balance,
                transaction_id=42,
                transaction_type="manual_bonus",
            )

    monkeypatch.setattr(router_module, "list_users", fake_list_users)
    monkeypatch.setattr(router_module, "get_user_stats", fake_get_user_stats)
    monkeypatch.setattr(router_module, "ban_user", fake_ban_user)
    monkeypatch.setattr(router_module, "unban_user", fake_unban_user)
    monkeypatch.setattr(router_module, "record_audit_event", fake_record_audit_event)
    monkeypatch.setattr(router_module, "list_audit_log", fake_list_audit_log)
    monkeypatch.setattr(router_module, "export_users_csv", fake_export_users_csv)
    monkeypatch.setattr(router_module, "TokenService", _FakeTokenService)

    app = create_app()

    async def _yield_session():
        yield session

    async def _yield_admin():
        return current_admin["user"]

    app.dependency_overrides[get_session] = _yield_session
    app.dependency_overrides[_settings_dep] = lambda: _Settings()
    app.dependency_overrides[get_current_admin] = _yield_admin
    app.dependency_overrides[bot_module.get_bot_client] = lambda: fake_bot

    return {
        "app": app,
        "users": users,
        "audit_log": audit_log,
        "session": session,
        "current_admin": current_admin,
        "fake_bot": fake_bot,
    }


async def _client(app: Any) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------- /admin/users


@pytest.mark.asyncio
async def test_list_users_returns_page(build_app) -> None:
    app = build_app["app"]
    async with await _client(app) as c:
        resp = await c.get("/api/v1/admin/users")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 3
    assert body["page"] == 1
    assert body["limit"] == 25
    assert body["has_more"] is False
    assert len(body["items"]) == 3
    usernames = {item["username"] for item in body["items"]}
    assert {"boss", "seer", "bob"} <= usernames


@pytest.mark.asyncio
async def test_list_users_filters_by_search(build_app) -> None:
    app = build_app["app"]
    async with await _client(app) as c:
        resp = await c.get("/api/v1/admin/users?search=bo")
    body = resp.json()
    assert resp.status_code == 200
    # matches "bob" and "boss" — both contain "bo"
    usernames = {item["username"] for item in body["items"]}
    assert {"bob", "boss"} == usernames


@pytest.mark.asyncio
async def test_list_users_rejects_invalid_sort(build_app) -> None:
    app = build_app["app"]
    async with await _client(app) as c:
        resp = await c.get("/api/v1/admin/users?sort=password")
    assert resp.status_code == 400
    assert "unsupported sort" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_list_users_rejects_pagination_overflow(build_app) -> None:
    app = build_app["app"]
    async with await _client(app) as c:
        resp = await c.get("/api/v1/admin/users?limit=10000")
    assert resp.status_code == 422  # max=200 hard cap


# ---------------------------------------------------------------- /admin/users/{id}


@pytest.mark.asyncio
async def test_get_user_returns_summary(build_app) -> None:
    app = build_app["app"]
    async with await _client(app) as c:
        resp = await c.get("/api/v1/admin/users/10")
    assert resp.status_code == 200
    assert resp.json()["telegram_id"] == 1000


@pytest.mark.asyncio
async def test_get_user_returns_404_when_missing(build_app) -> None:
    app = build_app["app"]
    async with await _client(app) as c:
        resp = await c.get("/api/v1/admin/users/99999")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "user_not_found"


@pytest.mark.asyncio
async def test_get_user_stats_returns_payload(build_app) -> None:
    app = build_app["app"]
    async with await _client(app) as c:
        resp = await c.get("/api/v1/admin/users/10/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["user"]["telegram_id"] == 1000
    assert body["transactions_total"] == 0
    assert body["recent_transactions"] == []
    assert body["referrals_count"] == 0


@pytest.mark.asyncio
async def test_get_user_stats_404_when_missing(build_app) -> None:
    app = build_app["app"]
    async with await _client(app) as c:
        resp = await c.get("/api/v1/admin/users/77/stats")
    assert resp.status_code == 404


# ---------------------------------------------------------------- add-tokens


@pytest.mark.asyncio
async def test_add_tokens_credits_balance_and_writes_audit(build_app) -> None:
    state = build_app
    app = state["app"]
    async with await _client(app) as c:
        resp = await c.post(
            "/api/v1/admin/users/10/add-tokens",
            json={"amount": 500, "reason": "compensation"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["new_balance"] == 600  # was 100 + 500
    assert body["transaction_id"] == 42
    assert state["users"][10].token_balance == 600
    assert any(
        log.action == "user.add_tokens" and log.target_user_id == 10
        for log in state["audit_log"]
    )
    assert state["session"].committed is True


@pytest.mark.asyncio
async def test_add_tokens_rejects_non_positive_amount(build_app) -> None:
    app = build_app["app"]
    async with await _client(app) as c:
        resp = await c.post(
            "/api/v1/admin/users/10/add-tokens",
            json={"amount": 0, "reason": "noop"},
        )
    assert resp.status_code == 422  # Pydantic gt=0


@pytest.mark.asyncio
async def test_add_tokens_returns_404_for_missing_user(build_app) -> None:
    app = build_app["app"]
    async with await _client(app) as c:
        resp = await c.post(
            "/api/v1/admin/users/9999/add-tokens",
            json={"amount": 10, "reason": "x"},
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_add_tokens_forbidden_for_analyst(build_app) -> None:
    state = build_app
    state["current_admin"]["user"] = FakeUser(id=3, telegram_id=300, role="analyst")
    async with await _client(state["app"]) as c:
        resp = await c.post(
            "/api/v1/admin/users/10/add-tokens",
            json={"amount": 10, "reason": "x"},
        )
    assert resp.status_code == 403


# ---------------------------------------------------------------- ban / unban


@pytest.mark.asyncio
async def test_ban_user_sets_flags_and_audits(build_app) -> None:
    state = build_app
    async with await _client(state["app"]) as c:
        resp = await c.post(
            "/api/v1/admin/users/10/ban",
            json={"reason": "spam"},
            headers={
                "X-Forwarded-For": "203.0.113.5, 10.0.0.1",
                "User-Agent": "tests/1.0",
            },
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_banned"] is True
    assert state["users"][10].is_banned is True
    log = state["audit_log"][-1]
    assert log.action == "user.ban"
    assert log.ip_address == "203.0.113.5"
    assert log.user_agent == "tests/1.0"


@pytest.mark.asyncio
async def test_ban_self_returns_400(build_app) -> None:
    state = build_app
    # current_admin is admin_super (id=1)
    async with await _client(state["app"]) as c:
        resp = await c.post("/api/v1/admin/users/1/ban", json={})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "cannot_ban_self"


@pytest.mark.asyncio
async def test_ban_other_admin_returns_403(build_app) -> None:
    state = build_app
    target = state["users"][10]
    target.role = "support_admin"
    async with await _client(state["app"]) as c:
        resp = await c.post("/api/v1/admin/users/10/ban", json={})
    assert resp.status_code == 403
    assert resp.json()["detail"] == "cannot_ban_admin"


@pytest.mark.asyncio
async def test_unban_clears_flags(build_app) -> None:
    state = build_app
    state["users"][10].is_banned = True
    state["users"][10].ban_reason = "test"
    async with await _client(state["app"]) as c:
        resp = await c.post("/api/v1/admin/users/10/unban")
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_banned"] is False
    assert body["ban_reason"] is None
    assert state["audit_log"][-1].action == "user.unban"


@pytest.mark.asyncio
async def test_ban_requires_support_admin(build_app) -> None:
    state = build_app
    state["current_admin"]["user"] = FakeUser(id=4, telegram_id=400, role="analyst")
    async with await _client(state["app"]) as c:
        resp = await c.post("/api/v1/admin/users/10/ban", json={})
    assert resp.status_code == 403


# ---------------------------------------------------------------- send-message


@pytest.mark.asyncio
async def test_send_message_delivers_via_bot(build_app) -> None:
    state = build_app
    async with await _client(state["app"]) as c:
        resp = await c.post(
            "/api/v1/admin/users/10/message",
            json={"text": "Hello there"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["delivered"] is True
    assert body["message_id"] == 777
    assert state["fake_bot"].calls[0]["chat_id"] == 1000
    log = state["audit_log"][-1]
    assert log.action == "user.send_message"
    assert log.payload["delivered"] is True


@pytest.mark.asyncio
async def test_send_message_returns_502_on_bot_failure(build_app, monkeypatch) -> None:
    state = build_app
    state["fake_bot"].fail = True
    state["fake_bot"].fail_description = "chat_not_found"
    async with await _client(state["app"]) as c:
        resp = await c.post(
            "/api/v1/admin/users/10/message",
            json={"text": "Hello there"},
        )
    assert resp.status_code == 502
    detail = resp.json()["detail"]
    assert detail["code"] == "telegram_send_failed"
    assert detail["description"] == "chat_not_found"
    # audit log still written, with delivered=False
    log = state["audit_log"][-1]
    assert log.action == "user.send_message"
    assert log.payload["delivered"] is False
    assert log.payload["error"] == "chat_not_found"


@pytest.mark.asyncio
async def test_send_message_requires_support_admin(build_app) -> None:
    state = build_app
    state["current_admin"]["user"] = FakeUser(id=4, telegram_id=400, role="analyst")
    async with await _client(state["app"]) as c:
        resp = await c.post(
            "/api/v1/admin/users/10/message",
            json={"text": "Hi"},
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_send_message_404_when_user_missing(build_app) -> None:
    state = build_app
    async with await _client(state["app"]) as c:
        resp = await c.post(
            "/api/v1/admin/users/9999/message",
            json={"text": "Hi"},
        )
    assert resp.status_code == 404


# ---------------------------------------------------------------- CSV export


@pytest.mark.asyncio
async def test_export_csv_returns_attachment_and_audits(build_app) -> None:
    state = build_app
    async with await _client(state["app"]) as c:
        resp = await c.get("/api/v1/admin/users/export.csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers.get("content-disposition", "")
    body = resp.text
    assert body.startswith("id,telegram_id,username")
    assert "bob" in body
    assert any(log.action == "users.export_csv" for log in state["audit_log"])


# ---------------------------------------------------------------- audit-log


@pytest.mark.asyncio
async def test_audit_log_endpoint_lists_entries(build_app) -> None:
    state = build_app
    # generate one entry via a ban
    async with await _client(state["app"]) as c:
        await c.post("/api/v1/admin/users/10/ban", json={"reason": "x"})
        resp = await c.get("/api/v1/admin/audit-log")
    body = resp.json()
    assert resp.status_code == 200
    assert body["total"] >= 1
    assert any(item["action"] == "user.ban" for item in body["items"])


@pytest.mark.asyncio
async def test_audit_log_filters_by_action(build_app) -> None:
    state = build_app
    async with await _client(state["app"]) as c:
        await c.post("/api/v1/admin/users/10/ban", json={"reason": "x"})
        await c.post("/api/v1/admin/users/10/unban")
        resp = await c.get("/api/v1/admin/audit-log?action=user.unban")
    body = resp.json()
    assert resp.status_code == 200
    assert all(item["action"] == "user.unban" for item in body["items"])
    assert body["total"] >= 1
