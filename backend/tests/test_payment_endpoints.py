"""Endpoint-level tests for ``/api/v1/payment/*``.

The :class:`PaymentService` is replaced with an in-memory stub so the
test can run without a database; the init-data auth flow follows the
same pattern as ``test_user_endpoints.py``.

What we verify:

* ``POST /payment/create-invoice`` returns the link the service produced.
* Missing/tampered init data → ``401``.
* Unknown package → ``404 package_not_found``.
* Telegram outage during invoice creation → ``502 telegram_api_error``.
* ``GET /payment/status/{invoice_id}`` reflects pending and completed.
* Unknown invoice → ``404 invoice_not_found``.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import pytest
from httpx import ASGITransport, AsyncClient

from app.bot.client import TelegramApiError
from app.services.payments import (
    InvoiceCreation,
    InvoiceNotFoundError,
    PackageNotFoundError,
    PaymentStatus,
)

BOT_TOKEN = "1234567890:TEST-AAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
JWT_SECRET = "test-secret"


class _Settings:
    app_env = "development"
    app_debug = True
    telegram_bot_token = BOT_TOKEN
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


@dataclass
class FakeUser:
    id: int
    telegram_id: int
    username: str = "alice"
    first_name: str = "Alice"
    last_name: str | None = None
    language_code: str = "en"
    referral_code: str = "REF-42"
    role: str = "user"
    is_banned: bool = False
    totp_enabled: bool = False
    totp_secret: str | None = None
    is_premium: bool = False
    premium_expires_at: datetime | None = None
    token_balance: int = 0
    total_tokens_purchased: int = 0
    total_tokens_spent: int = 0
    total_requests: int = 0
    last_active_at: datetime = datetime.now(UTC)
    last_login_at: datetime | None = None


class _FakePaymentService:
    """In-memory stand-in for :class:`PaymentService`.

    Holds a tiny state machine: ``create_invoice`` either yields a canned
    :class:`InvoiceCreation` or raises one of the configured errors;
    ``get_status`` returns the most-recently-created invoice's status.
    """

    _next_id = 100
    state: dict[str, Any] = {}

    def __init__(self, session: Any = None, *, client: Any = None) -> None:
        self.session = session
        self.client = client

    async def create_invoice(
        self,
        *,
        user_id: int,
        package_code: str,
    ) -> InvoiceCreation:
        if self.state.get("invoice_error"):
            raise self.state["invoice_error"]
        if package_code not in {"starter", "basic", "premium", "pro_monthly"}:
            raise PackageNotFoundError(package_code)
        _FakePaymentService._next_id += 1
        invoice = InvoiceCreation(
            invoice_id=f"pkg={package_code};u={user_id};n=fixed",
            payload=f"pkg={package_code};u={user_id};n=fixed",
            package_code=package_code,
            stars_amount=250,
            tokens_amount=500,
            telegram_invoice_link="https://t.me/$fake-link",
            transaction_id=_FakePaymentService._next_id,
            is_subscription=(package_code == "pro_monthly"),
        )
        self.state["last_invoice"] = invoice
        self.state["status"] = PaymentStatus(
            invoice_id=invoice.payload,
            status="pending",
            package_code=invoice.package_code,
            tokens_credited=invoice.tokens_amount,
            stars_amount=invoice.stars_amount,
            transaction_id=invoice.transaction_id,
            created_at=datetime.now(UTC),
            completed_at=None,
            telegram_payment_charge_id=None,
        )
        return invoice

    async def get_status(self, *, invoice_id: str, user_id: int) -> PaymentStatus:
        status = self.state.get("status")
        if status is None or status.invoice_id != invoice_id:
            raise InvoiceNotFoundError(invoice_id)
        return status


@pytest.fixture(autouse=True)
def _reset_state():
    _FakePaymentService.state.clear()
    yield
    _FakePaymentService.state.clear()


@pytest.fixture
def stub_user() -> FakeUser:
    return FakeUser(id=42, telegram_id=42)


@pytest.fixture
def build_app(monkeypatch, stub_user):
    """Wire the FastAPI app with stubbed DB/auth/PaymentService."""
    from app.api.v1 import bot as bot_route
    from app.api.v1 import payment as payment_module
    from app.auth import dependencies as deps
    from app.main import create_app
    from app.services import users as users_module

    settings = _Settings()
    store: dict[int, FakeUser] = {stub_user.telegram_id: stub_user}

    async def fake_upsert(_session, *, telegram_user, super_admin_ids):
        tid = int(telegram_user["id"])
        existing = store.get(tid)
        if existing is None:
            new_user = FakeUser(id=tid, telegram_id=tid)
            store[tid] = new_user
            return new_user, True
        return existing, False

    async def fake_find_by_id(_session, user_id):
        for u in store.values():
            if u.id == user_id:
                return u
        return None

    class _SessionStub:
        async def flush(self) -> None:
            return None

        async def commit(self) -> None:
            return None

        async def rollback(self) -> None:
            return None

        def add(self, obj: Any) -> None:
            return None

    async def fake_get_session():
        yield _SessionStub()

    monkeypatch.setattr(users_module, "upsert_telegram_user", fake_upsert)
    monkeypatch.setattr(users_module, "find_user_by_id", fake_find_by_id)
    monkeypatch.setattr(deps, "upsert_telegram_user", fake_upsert)
    monkeypatch.setattr(deps, "find_user_by_id", fake_find_by_id)
    monkeypatch.setattr(deps, "get_session", fake_get_session)
    monkeypatch.setattr(
        "app.core.config.get_settings", lambda: settings, raising=True
    )
    monkeypatch.setattr(deps, "get_settings", lambda: settings)

    # Replace PaymentService with our stub so endpoints don't touch the DB.
    monkeypatch.setattr(payment_module, "PaymentService", _FakePaymentService)

    # The payment endpoints depend on the bot client only for invoice creation;
    # the stub ignores it but FastAPI still resolves the dependency, so route
    # it through a no-op stand-in instead of trying to read settings.
    bot_route.reset_bot_client()
    original_get_bot_client = bot_route.get_bot_client

    class _FakeBot:
        pass

    app = create_app()

    from app.auth.dependencies import _settings_dep
    from app.core.database import get_session as real_get_session

    app.dependency_overrides[real_get_session] = fake_get_session
    app.dependency_overrides[_settings_dep] = lambda: settings
    app.dependency_overrides[original_get_bot_client] = lambda: _FakeBot()

    yield app

    bot_route.reset_bot_client()


def _build_init_data(telegram_id: int = 42) -> str:
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


async def _client(app: Any) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ----------------------------------------------- POST /payment/create-invoice


@pytest.mark.asyncio
async def test_create_invoice_returns_link(build_app) -> None:
    init = _build_init_data(telegram_id=42)
    async with await _client(build_app) as c:
        resp = await c.post(
            "/api/v1/payment/create-invoice",
            json={"package": "starter"},
            headers={"X-Telegram-Init-Data": init},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["telegram_invoice_link"] == "https://t.me/$fake-link"
    assert body["stars_amount"] == 250
    assert body["tokens_amount"] == 500
    assert body["is_subscription"] is False
    assert body["invoice_id"].startswith("pkg=starter")


@pytest.mark.asyncio
async def test_create_invoice_marks_subscription_package(build_app) -> None:
    init = _build_init_data(telegram_id=42)
    async with await _client(build_app) as c:
        resp = await c.post(
            "/api/v1/payment/create-invoice",
            json={"package": "pro_monthly"},
            headers={"X-Telegram-Init-Data": init},
        )
    assert resp.status_code == 200
    assert resp.json()["is_subscription"] is True


@pytest.mark.asyncio
async def test_create_invoice_requires_init_data(build_app) -> None:
    async with await _client(build_app) as c:
        resp = await c.post(
            "/api/v1/payment/create-invoice",
            json={"package": "starter"},
        )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "missing_init_data"


@pytest.mark.asyncio
async def test_create_invoice_rejects_tampered_init_data(build_app) -> None:
    init = _build_init_data().replace("Alice", "Mallory")
    async with await _client(build_app) as c:
        resp = await c.post(
            "/api/v1/payment/create-invoice",
            json={"package": "starter"},
            headers={"X-Telegram-Init-Data": init},
        )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "invalid_init_data"


@pytest.mark.asyncio
async def test_create_invoice_unknown_package_returns_404(build_app) -> None:
    init = _build_init_data()
    async with await _client(build_app) as c:
        resp = await c.post(
            "/api/v1/payment/create-invoice",
            json={"package": "ghost-pack"},
            headers={"X-Telegram-Init-Data": init},
        )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "package_not_found"


@pytest.mark.asyncio
async def test_create_invoice_telegram_failure_returns_502(build_app) -> None:
    _FakePaymentService.state["invoice_error"] = TelegramApiError(
        "createInvoiceLink", "telegram down"
    )
    init = _build_init_data()
    async with await _client(build_app) as c:
        resp = await c.post(
            "/api/v1/payment/create-invoice",
            json={"package": "starter"},
            headers={"X-Telegram-Init-Data": init},
        )
    assert resp.status_code == 502
    assert resp.json()["detail"] == "telegram_api_error"


@pytest.mark.asyncio
async def test_create_invoice_rejects_blank_package(build_app) -> None:
    init = _build_init_data()
    async with await _client(build_app) as c:
        resp = await c.post(
            "/api/v1/payment/create-invoice",
            json={"package": ""},
            headers={"X-Telegram-Init-Data": init},
        )
    # Pydantic validation: min_length=1.
    assert resp.status_code == 422


# --------------------------------------------- GET /payment/status/{invoice_id}


@pytest.mark.asyncio
async def test_get_status_returns_pending_after_create(build_app) -> None:
    init = _build_init_data()
    async with await _client(build_app) as c:
        create = await c.post(
            "/api/v1/payment/create-invoice",
            json={"package": "starter"},
            headers={"X-Telegram-Init-Data": init},
        )
        assert create.status_code == 200
        invoice_id = create.json()["invoice_id"]
        status = await c.get(
            f"/api/v1/payment/status/{invoice_id}",
            headers={"X-Telegram-Init-Data": init},
        )
    assert status.status_code == 200
    body = status.json()
    assert body["status"] == "pending"
    assert body["tokens_credited"] == 0  # masked while pending
    assert body["telegram_payment_charge_id"] is None


@pytest.mark.asyncio
async def test_get_status_reflects_completed_invoice(build_app) -> None:
    init = _build_init_data()
    async with await _client(build_app) as c:
        create = await c.post(
            "/api/v1/payment/create-invoice",
            json={"package": "starter"},
            headers={"X-Telegram-Init-Data": init},
        )
        invoice_id = create.json()["invoice_id"]

        # Flip the stub to "completed" to simulate the success webhook.
        snap = _FakePaymentService.state["status"]
        _FakePaymentService.state["status"] = PaymentStatus(
            invoice_id=snap.invoice_id,
            status="completed",
            package_code=snap.package_code,
            tokens_credited=snap.tokens_credited,
            stars_amount=snap.stars_amount,
            transaction_id=snap.transaction_id,
            created_at=snap.created_at,
            completed_at=datetime.now(UTC),
            telegram_payment_charge_id="charge-ok",
        )

        status = await c.get(
            f"/api/v1/payment/status/{invoice_id}",
            headers={"X-Telegram-Init-Data": init},
        )
    body = status.json()
    assert body["status"] == "completed"
    assert body["tokens_credited"] == 500
    assert body["telegram_payment_charge_id"] == "charge-ok"


@pytest.mark.asyncio
async def test_get_status_unknown_invoice_returns_404(build_app) -> None:
    init = _build_init_data()
    async with await _client(build_app) as c:
        resp = await c.get(
            "/api/v1/payment/status/pkg=starter;u=999;n=ghost",
            headers={"X-Telegram-Init-Data": init},
        )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "invoice_not_found"


@pytest.mark.asyncio
async def test_get_status_requires_init_data(build_app) -> None:
    async with await _client(build_app) as c:
        resp = await c.get("/api/v1/payment/status/anything")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "missing_init_data"
