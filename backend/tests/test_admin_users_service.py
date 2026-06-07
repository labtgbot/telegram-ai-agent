"""Database-backed integration tests for the admin-users service.

Covers the SQL building blocks behind the CRM Users section: filtered
listing, sort + pagination, per-user stats aggregation, ban / unban with
audit, CSV export and audit-log query.  Tests skip automatically when
no PostgreSQL is available (see ``conftest.py``).
"""
from __future__ import annotations

import csv
import io
from datetime import UTC, datetime, timedelta

import pytest

from app.models.admin_audit_log import AdminAuditLog
from app.models.token_usage_log import TokenUsageLog
from app.models.transaction import Transaction
from app.models.user import User
from app.services.admin_users import (
    CannotTargetAdminError,
    CannotTargetSelfError,
    InvalidFilterError,
    UserListFilters,
    UserNotFoundError,
    ban_user,
    export_users_csv,
    get_user_stats,
    list_audit_log,
    list_users,
    record_audit_event,
    unban_user,
)

# ---------------------------------------------------------------- helpers


_NEXT_TID = 9_100_000


def _next_telegram_id() -> int:
    global _NEXT_TID
    _NEXT_TID += 1
    return _NEXT_TID


async def _make_user(
    session,
    *,
    username: str | None = None,
    role: str = "user",
    is_premium: bool = False,
    is_banned: bool = False,
    referred_by: int | None = None,
    token_balance: int = 0,
    first_name: str | None = None,
) -> User:
    tid = _next_telegram_id()
    user = User(
        telegram_id=tid,
        username=username,
        first_name=first_name,
        referral_code=f"AU-{tid}",
        role=role,
        is_premium=is_premium,
        is_banned=is_banned,
        referred_by=referred_by,
        token_balance=token_balance,
    )
    session.add(user)
    await session.flush()
    return user


# ---------------------------------------------------------------- list_users


@pytest.mark.asyncio
async def test_list_users_returns_pagination(db_session):
    a = await _make_user(db_session, username="alice")
    b = await _make_user(db_session, username="bob")
    c = await _make_user(db_session, username="carol")

    # Sort descending so the three users we just created (highest telegram_ids)
    # land on page 1, even if the test database already has older fixtures.
    page = await list_users(db_session, page=1, limit=2, sort="telegram_id", direction="desc")
    ids = [u.id for u in page.items]
    assert len(page.items) == 2
    assert page.total >= 3
    assert page.has_more is True
    assert {a.id, b.id, c.id} & set(ids)


@pytest.mark.asyncio
async def test_list_users_filter_by_premium(db_session):
    await _make_user(db_session, username="free1", is_premium=False)
    pro = await _make_user(db_session, username="pro1", is_premium=True)

    page = await list_users(
        db_session, filters=UserListFilters(is_premium=True), limit=200
    )
    assert pro.id in {u.id for u in page.items}
    assert all(u.is_premium for u in page.items)


@pytest.mark.asyncio
async def test_list_users_filter_by_banned(db_session):
    await _make_user(db_session, username="okay", is_banned=False)
    bad = await _make_user(db_session, username="bad", is_banned=True)

    page = await list_users(
        db_session, filters=UserListFilters(is_banned=True), limit=200
    )
    assert bad.id in {u.id for u in page.items}
    assert all(u.is_banned for u in page.items)


@pytest.mark.asyncio
async def test_list_users_search_by_username_prefix(db_session):
    await _make_user(db_session, username="alpha_one")
    target = await _make_user(db_session, username="alpha_two")
    await _make_user(db_session, username="omega_three")

    page = await list_users(
        db_session, filters=UserListFilters(search="alpha"), limit=200
    )
    usernames = {u.username for u in page.items}
    assert target.username in usernames
    assert "omega_three" not in usernames


@pytest.mark.asyncio
async def test_list_users_search_by_at_prefix(db_session):
    target = await _make_user(db_session, username="betauser")
    page = await list_users(
        db_session, filters=UserListFilters(search="@beta"), limit=200
    )
    assert target.id in {u.id for u in page.items}


@pytest.mark.asyncio
async def test_list_users_search_by_telegram_id(db_session):
    target = await _make_user(db_session, username="numeric")
    page = await list_users(
        db_session,
        filters=UserListFilters(search=str(target.telegram_id)),
        limit=10,
    )
    assert [u.id for u in page.items] == [target.id]


@pytest.mark.asyncio
async def test_list_users_rejects_invalid_sort(db_session):
    with pytest.raises(InvalidFilterError):
        await list_users(db_session, sort="password")  # type: ignore[arg-type]


# ---------------------------------------------------------------- stats


@pytest.mark.asyncio
async def test_get_user_stats_aggregates_transactions_and_usage(db_session):
    user = await _make_user(db_session, username="statsy", token_balance=500)

    # Add two transactions
    db_session.add_all(
        [
            Transaction(
                user_id=user.id,
                transaction_type="purchase",
                tokens_amount=100,
                payment_status="completed",
                completed_at=datetime.now(UTC),
            ),
            Transaction(
                user_id=user.id,
                transaction_type="spend",
                tokens_amount=20,
                payment_status="completed",
                completed_at=datetime.now(UTC),
            ),
        ]
    )
    # Add two usage rows for the same service, one for another
    db_session.add_all(
        [
            TokenUsageLog(
                user_id=user.id, service_type="text", tokens_consumed=10
            ),
            TokenUsageLog(
                user_id=user.id, service_type="text", tokens_consumed=15
            ),
            TokenUsageLog(
                user_id=user.id, service_type="image", tokens_consumed=50
            ),
        ]
    )
    # Referrals
    await _make_user(db_session, username="ref1", referred_by=user.id)
    await _make_user(db_session, username="ref2", referred_by=user.id)
    await db_session.flush()

    stats = await get_user_stats(db_session, user.id)
    assert stats.user.id == user.id
    assert stats.transactions_total == 2
    assert len(stats.recent_transactions) == 2
    services = {row.service_type: row for row in stats.services_usage}
    assert services["text"].requests == 2
    assert services["text"].tokens_spent == 25
    assert services["image"].tokens_spent == 50
    assert stats.referrals_count == 2
    assert len(stats.recent_referrals) == 2


@pytest.mark.asyncio
async def test_get_user_stats_raises_when_missing(db_session):
    with pytest.raises(UserNotFoundError):
        await get_user_stats(db_session, 999_999_999)


# ---------------------------------------------------------------- ban / unban


@pytest.mark.asyncio
async def test_ban_user_marks_user_and_writes_audit_row(db_session):
    admin = await _make_user(db_session, username="bossy", role="support_admin")
    victim = await _make_user(db_session, username="victim", role="user")

    banned = await ban_user(
        db_session,
        admin=admin,
        user_id=victim.id,
        reason="spamming",
        banned_until=datetime.now(UTC) + timedelta(days=1),
        ip_address="203.0.113.5",
        user_agent="tests/1.0",
    )
    assert banned.is_banned is True
    assert banned.ban_reason == "spamming"
    assert banned.banned_until is not None

    page = await list_audit_log(db_session, target_user_id=victim.id, limit=10)
    assert page.total == 1
    log = page.items[0]
    assert log.action == "user.ban"
    assert log.admin_id == admin.id
    assert log.payload["reason"] == "spamming"
    assert log.ip_address == "203.0.113.5"
    assert log.user_agent == "tests/1.0"


@pytest.mark.asyncio
async def test_ban_user_refuses_self(db_session):
    admin = await _make_user(db_session, username="self_admin", role="support_admin")
    with pytest.raises(CannotTargetSelfError):
        await ban_user(db_session, admin=admin, user_id=admin.id)


@pytest.mark.asyncio
async def test_ban_user_refuses_other_admins(db_session):
    admin = await _make_user(db_session, username="sa1", role="support_admin")
    other = await _make_user(db_session, username="sa2", role="super_admin")
    with pytest.raises(CannotTargetAdminError):
        await ban_user(db_session, admin=admin, user_id=other.id)


@pytest.mark.asyncio
async def test_unban_user_clears_flags_and_audits(db_session):
    admin = await _make_user(db_session, username="ub_admin", role="support_admin")
    victim = await _make_user(
        db_session, username="ub_victim", role="user", is_banned=True
    )
    victim.ban_reason = "old"
    await db_session.flush()

    res = await unban_user(
        db_session,
        admin=admin,
        user_id=victim.id,
        ip_address="198.51.100.7",
    )
    assert res.is_banned is False
    assert res.ban_reason is None

    page = await list_audit_log(
        db_session, target_user_id=victim.id, action="user.unban"
    )
    assert page.total == 1
    assert page.items[0].ip_address == "198.51.100.7"


@pytest.mark.asyncio
async def test_unban_raises_on_missing_user(db_session):
    admin = await _make_user(db_session, username="ub_admin2", role="support_admin")
    with pytest.raises(UserNotFoundError):
        await unban_user(db_session, admin=admin, user_id=999_888_777)


# ---------------------------------------------------------------- audit log


@pytest.mark.asyncio
async def test_record_audit_event_persists_row(db_session):
    admin = await _make_user(db_session, username="auditor", role="super_admin")
    target = await _make_user(db_session, username="target_x")

    log = await record_audit_event(
        db_session,
        admin=admin,
        target_user_id=target.id,
        action="user.add_tokens",
        payload={"amount": 100, "reason": "test"},
        ip_address="10.0.0.1",
        user_agent="agent/1.0",
    )
    assert log.id > 0
    assert log.action == "user.add_tokens"
    assert log.payload == {"amount": 100, "reason": "test"}
    assert isinstance(log, AdminAuditLog)


@pytest.mark.asyncio
async def test_audit_log_filters_by_admin_action_target(db_session):
    a1 = await _make_user(db_session, username="a1", role="super_admin")
    a2 = await _make_user(db_session, username="a2", role="super_admin")
    t = await _make_user(db_session, username="t")

    await record_audit_event(
        db_session, admin=a1, target_user_id=t.id, action="user.ban", payload=None
    )
    await record_audit_event(
        db_session, admin=a2, target_user_id=t.id, action="user.unban", payload=None
    )
    await record_audit_event(
        db_session,
        admin=a1,
        target_user_id=None,
        action="users.export_csv",
        payload={"limit": 10},
    )

    only_a1 = await list_audit_log(db_session, admin_id=a1.id, limit=20)
    assert {r.action for r in only_a1.items} >= {"user.ban", "users.export_csv"}
    assert all(r.admin_id == a1.id for r in only_a1.items)

    only_bans = await list_audit_log(db_session, action="user.ban", limit=20)
    assert all(r.action == "user.ban" for r in only_bans.items)

    for_target = await list_audit_log(db_session, target_user_id=t.id, limit=20)
    assert all(r.target_user_id == t.id for r in for_target.items)


# ---------------------------------------------------------------- CSV export


@pytest.mark.asyncio
async def test_export_users_csv_writes_header_and_rows(db_session):
    u1 = await _make_user(db_session, username="exp1")
    u2 = await _make_user(db_session, username="exp2", is_banned=True)

    csv_text = await export_users_csv(
        db_session, filters=UserListFilters(is_banned=True), limit=10
    )
    lines = csv_text.strip().split("\n")
    header = lines[0]
    assert header.startswith("id,telegram_id,username,")
    rows = list(csv.DictReader(io.StringIO(csv_text)))
    exported_ids = {int(row["id"]) for row in rows}
    # contains the banned user
    assert u2.id in exported_ids
    # excludes the non-banned user
    assert u1.id not in exported_ids
