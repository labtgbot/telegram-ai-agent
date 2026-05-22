"""Endpoint-level tests for ``/api/v1/admin/analytics/*`` (issue #27).

The service layer is exercised against PostgreSQL in
``test_admin_analytics_service.py``.  Here we stub every service call to
keep the suite fast and free of DB setup, focusing on the HTTP wiring:
RBAC, query-param validation, error mapping, audit logging on CSV
export, and the response payload shape.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

# Break the ``app.services.payments`` ↔ ``app.bot.handlers`` import cycle
# the same way other admin tests do.
from app.bot.client import TelegramApiError  # noqa: F401

JWT_SECRET = "test-secret"


# ---------------------------------------------------------------- settings stub


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


# ---------------------------------------------------------------- fakes


class FakeUser:
    def __init__(
        self,
        *,
        id: int,
        telegram_id: int,
        role: str = "analyst",
    ) -> None:
        self.id = id
        self.telegram_id = telegram_id
        self.username = f"u{telegram_id}"
        self.first_name = "First"
        self.last_name = "Last"
        self.language_code = "en"
        self.role = role
        self.is_premium = False
        self.is_banned = False
        self.ban_reason: str | None = None
        self.banned_until: datetime | None = None
        self.token_balance = 0
        self.total_tokens_purchased = 0
        self.total_tokens_spent = 0
        self.total_requests = 0
        self.referral_code = f"REF-{telegram_id}"
        self.referred_by: int | None = None
        self.created_at = datetime.now(UTC)
        self.last_active_at: datetime | None = datetime.now(UTC)
        self.last_login_at: datetime | None = None


class FakeAuditLog:
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


class FakeSession:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True

    async def execute(self, *_a, **_kw):  # pragma: no cover - never reached
        raise AssertionError("session.execute should be stubbed by tests")


# ---------------------------------------------------------------- canned data


def _sample_revenue() -> Any:
    from app.services.analytics import RevenuePoint, RevenueSummary

    points = [
        RevenuePoint(
            bucket=date(2026, 5, 1),
            stars=500,
            usd=Decimal("12.50"),
            tokens_sold=5_000,
            purchases=3,
        ),
        RevenuePoint(
            bucket=date(2026, 5, 2),
            stars=300,
            usd=Decimal("7.20"),
            tokens_sold=3_000,
            purchases=2,
        ),
    ]
    return RevenueSummary(
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 2),
        group_by="day",
        total_stars=800,
        total_usd=Decimal("19.70"),
        total_tokens_sold=8_000,
        total_purchases=5,
        points=points,
    )


def _sample_user_behavior() -> Any:
    from app.services.analytics import FunnelStage, RetentionRow, UserBehavior

    funnel = [
        FunnelStage(
            key="registered",
            label="Registered",
            users=100,
            conversion_from_previous=1.0,
            conversion_from_top=1.0,
        ),
        FunnelStage(
            key="activated",
            label="Used the bot",
            users=80,
            conversion_from_previous=0.8,
            conversion_from_top=0.8,
        ),
        FunnelStage(
            key="paid",
            label="Made a purchase",
            users=20,
            conversion_from_previous=0.25,
            conversion_from_top=0.2,
        ),
        FunnelStage(
            key="repeat",
            label="Repeat purchase",
            users=5,
            conversion_from_previous=0.25,
            conversion_from_top=0.05,
        ),
        FunnelStage(
            key="premium",
            label="Premium",
            users=2,
            conversion_from_previous=0.4,
            conversion_from_top=0.02,
        ),
    ]
    retention = [
        RetentionRow(
            cohort=date(2026, 4, 27),
            cohort_size=40,
            retained=[40, 30, 20, 10],
            rates=[1.0, 0.75, 0.5, 0.25],
        ),
    ]
    return UserBehavior(
        start_date=date(2026, 4, 1),
        end_date=date(2026, 5, 1),
        funnel=funnel,
        retention_weeks=4,
        retention=retention,
    )


def _sample_ltv() -> Any:
    from app.services.analytics import LtvCohort, LtvSummary

    cohorts = [
        LtvCohort(
            cohort=date(2026, 3, 1),
            cohort_size=50,
            paying_users=10,
            revenue_stars=2_000,
            revenue_usd=Decimal("50.00"),
            ltv_stars=40.0,
            ltv_usd=1.0,
            avg_revenue_per_paying=200.0,
        ),
    ]
    return LtvSummary(
        months=6,
        cohorts=cohorts,
        overall_arpu_stars=40.0,
        overall_arpu_usd=1.0,
        overall_paying_rate=0.2,
    )


def _sample_tokens() -> Any:
    from app.services.analytics import TokenUsagePoint, TokenUsageSummary

    services = [
        TokenUsagePoint(
            service_type="image_generation",
            requests=120,
            tokens_spent=6_000,
            share=0.6,
        ),
        TokenUsagePoint(
            service_type="video_generation",
            requests=40,
            tokens_spent=4_000,
            share=0.4,
        ),
    ]
    return TokenUsageSummary(
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 7),
        total_requests=160,
        total_tokens_spent=10_000,
        services=services,
    )


# ---------------------------------------------------------------- fixtures


@pytest.fixture
def admin_analyst() -> FakeUser:
    return FakeUser(id=2, telegram_id=200, role="analyst")


@pytest.fixture
def build_app(monkeypatch, admin_analyst):
    """Compose an ASGI app with the admin-analytics router fully stubbed."""
    from app.api.v1 import admin_analytics as router_module
    from app.auth.dependencies import _settings_dep, get_current_admin
    from app.core.database import get_session
    from app.main import create_app
    from app.services.analytics import (
        InvalidRangeError,
        UnsupportedGroupingError,
    )

    audit_log: list[FakeAuditLog] = []
    session = FakeSession()
    current_admin: dict[str, FakeUser] = {"user": admin_analyst}
    calls: dict[str, list[dict[str, Any]]] = {
        "revenue": [],
        "user_behavior": [],
        "ltv": [],
        "tokens": [],
        "csv": [],
    }

    raise_revenue: dict[str, Exception | None] = {"err": None}
    raise_behavior: dict[str, Exception | None] = {"err": None}
    raise_tokens: dict[str, Exception | None] = {"err": None}

    async def fake_get_revenue_summary(_session, **kwargs):  # noqa: ANN001
        calls["revenue"].append(kwargs)
        if raise_revenue["err"] is not None:
            raise raise_revenue["err"]
        # Mirror what the real service does for unsupported groupings.
        group_by = kwargs.get("group_by", "day")
        if group_by not in {"day", "week", "month"}:
            raise UnsupportedGroupingError(
                f"unsupported group_by={group_by!r}"
            )
        return _sample_revenue()

    async def fake_get_user_behavior(_session, **kwargs):  # noqa: ANN001
        calls["user_behavior"].append(kwargs)
        if raise_behavior["err"] is not None:
            raise raise_behavior["err"]
        return _sample_user_behavior()

    async def fake_get_ltv_summary(_session, **kwargs):  # noqa: ANN001
        calls["ltv"].append(kwargs)
        return _sample_ltv()

    async def fake_get_token_usage(_session, **kwargs):  # noqa: ANN001
        calls["tokens"].append(kwargs)
        if raise_tokens["err"] is not None:
            raise raise_tokens["err"]
        return _sample_tokens()

    def fake_revenue_csv(summary):
        calls["csv"].append({"summary": summary})
        return (
            "bucket,purchases,stars,usd,tokens_sold\n"
            "2026-05-01,3,500,12.50,5000\n"
            "2026-05-02,2,300,7.20,3000\n"
        )

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

    monkeypatch.setattr(router_module, "get_revenue_summary", fake_get_revenue_summary)
    monkeypatch.setattr(router_module, "get_user_behavior", fake_get_user_behavior)
    monkeypatch.setattr(router_module, "get_ltv_summary", fake_get_ltv_summary)
    monkeypatch.setattr(router_module, "get_token_usage", fake_get_token_usage)
    monkeypatch.setattr(router_module, "revenue_csv", fake_revenue_csv)
    monkeypatch.setattr(router_module, "record_audit_event", fake_record_audit_event)

    app = create_app()

    async def _yield_session():
        yield session

    async def _yield_admin():
        return current_admin["user"]

    app.dependency_overrides[get_session] = _yield_session
    app.dependency_overrides[_settings_dep] = lambda: _Settings()
    app.dependency_overrides[get_current_admin] = _yield_admin

    return {
        "app": app,
        "session": session,
        "audit_log": audit_log,
        "current_admin": current_admin,
        "calls": calls,
        "raise_revenue": raise_revenue,
        "raise_behavior": raise_behavior,
        "raise_tokens": raise_tokens,
        "InvalidRangeError": InvalidRangeError,
        "UnsupportedGroupingError": UnsupportedGroupingError,
    }


async def _client(app: Any) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------- /revenue


@pytest.mark.asyncio
async def test_revenue_returns_summary(build_app) -> None:
    app = build_app["app"]
    async with await _client(app) as c:
        resp = await c.get(
            "/api/v1/admin/analytics/revenue",
            params={
                "start_date": "2026-05-01",
                "end_date": "2026-05-02",
                "group_by": "day",
            },
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["group_by"] == "day"
    assert body["start_date"] == "2026-05-01"
    assert body["end_date"] == "2026-05-02"
    assert body["total_stars"] == 800
    assert body["total_usd"] == "19.70"
    assert body["total_purchases"] == 5
    assert len(body["points"]) == 2
    first = body["points"][0]
    assert first["bucket"] == "2026-05-01"
    assert first["stars"] == 500
    assert first["usd"] == "12.50"
    # Verify the service received the parsed query params.
    call = build_app["calls"]["revenue"][-1]
    assert call["start_date"] == date(2026, 5, 1)
    assert call["end_date"] == date(2026, 5, 2)
    assert call["group_by"] == "day"


@pytest.mark.asyncio
async def test_revenue_defaults_group_by_to_day(build_app) -> None:
    app = build_app["app"]
    async with await _client(app) as c:
        resp = await c.get("/api/v1/admin/analytics/revenue")
    assert resp.status_code == 200
    assert build_app["calls"]["revenue"][-1]["group_by"] == "day"


@pytest.mark.asyncio
async def test_revenue_rejects_invalid_group_by(build_app) -> None:
    app = build_app["app"]
    async with await _client(app) as c:
        resp = await c.get(
            "/api/v1/admin/analytics/revenue",
            params={"group_by": "year"},
        )
    # FastAPI's regex validator rejects before the service is called.
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_revenue_maps_inverted_range_to_400(build_app) -> None:
    state = build_app
    state["raise_revenue"]["err"] = state["InvalidRangeError"](
        "start_date must not be after end_date"
    )
    async with await _client(state["app"]) as c:
        resp = await c.get(
            "/api/v1/admin/analytics/revenue",
            params={"start_date": "2026-05-10", "end_date": "2026-05-01"},
        )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "invalid_range"
    assert "must not be after" in detail["message"]


@pytest.mark.asyncio
async def test_revenue_requires_admin_token(build_app) -> None:
    """When the dependency override is removed the real one rejects unauthed requests."""
    from app.auth.dependencies import get_current_admin

    app = build_app["app"]
    app.dependency_overrides.pop(get_current_admin, None)
    async with await _client(app) as c:
        resp = await c.get("/api/v1/admin/analytics/revenue")
    assert resp.status_code == 401


# ---------------------------------------------------------------- /user-behavior


@pytest.mark.asyncio
async def test_user_behavior_returns_funnel_and_retention(build_app) -> None:
    app = build_app["app"]
    async with await _client(app) as c:
        resp = await c.get(
            "/api/v1/admin/analytics/user-behavior",
            params={"retention_weeks": 4},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["retention_weeks"] == 4
    funnel_keys = [s["key"] for s in body["funnel"]]
    assert funnel_keys == [
        "registered",
        "activated",
        "paid",
        "repeat",
        "premium",
    ]
    paid = next(s for s in body["funnel"] if s["key"] == "paid")
    assert paid["users"] == 20
    assert paid["conversion_from_top"] == pytest.approx(0.2)
    assert len(body["retention"]) == 1
    row = body["retention"][0]
    assert row["cohort"] == "2026-04-27"
    assert row["cohort_size"] == 40
    assert row["rates"] == [1.0, 0.75, 0.5, 0.25]
    call = build_app["calls"]["user_behavior"][-1]
    assert call["retention_weeks"] == 4


@pytest.mark.asyncio
async def test_user_behavior_rejects_out_of_range_retention(build_app) -> None:
    app = build_app["app"]
    async with await _client(app) as c:
        resp = await c.get(
            "/api/v1/admin/analytics/user-behavior",
            params={"retention_weeks": 999},
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_user_behavior_maps_invalid_range_to_400(build_app) -> None:
    state = build_app
    state["raise_behavior"]["err"] = state["InvalidRangeError"]("bad range")
    async with await _client(state["app"]) as c:
        resp = await c.get("/api/v1/admin/analytics/user-behavior")
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_range"


# ---------------------------------------------------------------- /ltv


@pytest.mark.asyncio
async def test_ltv_returns_cohorts(build_app) -> None:
    app = build_app["app"]
    async with await _client(app) as c:
        resp = await c.get("/api/v1/admin/analytics/ltv", params={"months": 6})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["months"] == 6
    assert body["overall_arpu_stars"] == pytest.approx(40.0)
    assert body["overall_arpu_usd"] == pytest.approx(1.0)
    assert body["overall_paying_rate"] == pytest.approx(0.2)
    assert len(body["cohorts"]) == 1
    cohort = body["cohorts"][0]
    assert cohort["cohort"] == "2026-03-01"
    assert cohort["cohort_size"] == 50
    assert cohort["paying_users"] == 10
    assert cohort["revenue_usd"] == "50.00"
    assert cohort["ltv_stars"] == pytest.approx(40.0)
    assert build_app["calls"]["ltv"][-1]["months"] == 6


@pytest.mark.asyncio
async def test_ltv_rejects_out_of_range_months(build_app) -> None:
    app = build_app["app"]
    async with await _client(app) as c:
        resp = await c.get("/api/v1/admin/analytics/ltv", params={"months": 99})
    assert resp.status_code == 422


# ---------------------------------------------------------------- /tokens


@pytest.mark.asyncio
async def test_tokens_returns_breakdown(build_app) -> None:
    app = build_app["app"]
    async with await _client(app) as c:
        resp = await c.get(
            "/api/v1/admin/analytics/tokens",
            params={"start_date": "2026-05-01", "end_date": "2026-05-07"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_requests"] == 160
    assert body["total_tokens_spent"] == 10_000
    services = body["services"]
    assert {s["service_type"] for s in services} == {
        "image_generation",
        "video_generation",
    }
    image = next(s for s in services if s["service_type"] == "image_generation")
    assert image["share"] == pytest.approx(0.6)
    call = build_app["calls"]["tokens"][-1]
    assert call["start_date"] == date(2026, 5, 1)
    assert call["end_date"] == date(2026, 5, 7)


@pytest.mark.asyncio
async def test_tokens_maps_invalid_range_to_400(build_app) -> None:
    state = build_app
    state["raise_tokens"]["err"] = state["InvalidRangeError"]("bad")
    async with await _client(state["app"]) as c:
        resp = await c.get("/api/v1/admin/analytics/tokens")
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_range"


# ---------------------------------------------------------------- /export.csv


@pytest.mark.asyncio
async def test_export_csv_returns_attachment_and_audits(build_app) -> None:
    from app.services.analytics import ANALYTICS_AUDIT_EXPORT

    state = build_app
    async with await _client(state["app"]) as c:
        resp = await c.get(
            "/api/v1/admin/analytics/export.csv",
            params={
                "start_date": "2026-05-01",
                "end_date": "2026-05-02",
                "group_by": "day",
            },
            headers={
                "X-Forwarded-For": "198.51.100.7, 10.0.0.1",
                "User-Agent": "tests/1.0",
            },
        )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/csv")
    disposition = resp.headers.get("content-disposition", "")
    assert "attachment" in disposition
    assert "revenue-2026-05-01-2026-05-02-day.csv" in disposition
    body = resp.text
    assert body.startswith("bucket,purchases,stars,usd,tokens_sold")
    assert "2026-05-01,3,500,12.50,5000" in body

    # Audit row written with the parsed params.
    assert state["session"].committed is True
    audit = state["audit_log"][-1]
    assert audit.action == ANALYTICS_AUDIT_EXPORT
    assert audit.target_user_id is None
    assert audit.payload == {
        "kind": "revenue",
        "start_date": "2026-05-01",
        "end_date": "2026-05-02",
        "group_by": "day",
        "rows": 2,
    }
    assert audit.ip_address == "198.51.100.7"
    assert audit.user_agent == "tests/1.0"


@pytest.mark.asyncio
async def test_export_csv_maps_invalid_range_to_400(build_app) -> None:
    state = build_app
    state["raise_revenue"]["err"] = state["InvalidRangeError"]("bad range")
    async with await _client(state["app"]) as c:
        resp = await c.get("/api/v1/admin/analytics/export.csv")
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_range"
    # No audit row should be written when the export aborts.
    assert state["audit_log"] == []
    assert state["session"].committed is False


@pytest.mark.asyncio
async def test_export_csv_rejects_invalid_group_by_via_regex(build_app) -> None:
    state = build_app
    async with await _client(state["app"]) as c:
        resp = await c.get(
            "/api/v1/admin/analytics/export.csv",
            params={"group_by": "year"},
        )
    assert resp.status_code == 422
    assert state["audit_log"] == []
