"""Admin system-settings service (Phase 3, issue #29).

Powers the CRM "System Settings" section:

* maintenance mode toggle (banner shown to users when the bot is paused);
* rate-limit catalog (read/write the ``rate_limits`` setting consumed by
  :mod:`app.services.rate_limit_config`);
* composio integration config (list of enabled tool slugs + per-tool
  settings, stored as JSONB);
* admin users list and role management (with safety rails so the last
  super-admin cannot demote themselves).

All mutations write a row to ``admin_audit_logs`` so support engineers
have a tamper-evident change history.

Each setting lives behind a stable key in :data:`SETTINGS_REGISTRY` —
:class:`AdminSetting` rows are upserted by key with the new value, the
admin that authored the change and the change timestamp.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import Role
from app.core.logging import get_logger
from app.models.admin_audit_log import AdminAuditLog
from app.models.admin_setting import AdminSetting
from app.models.user import User
from app.services.rate_limit_config import (
    ADMIN_SETTING_KEY as RATE_LIMITS_KEY,
    DEFAULT_RATE_LIMITS,
    KNOWN_PLANS,
    merge_overrides,
)

logger = get_logger(__name__)


# ----------------------------------------------------------------- constants

MAINTENANCE_SETTING_KEY = "maintenance_mode"
COMPOSIO_SETTING_KEY = "composio_config"

# Audit actions.
MAINTENANCE_AUDIT_UPDATE = "settings.maintenance.update"
RATE_LIMITS_AUDIT_UPDATE = "settings.rate_limits.update"
COMPOSIO_AUDIT_UPDATE = "settings.composio.update"
ADMIN_ROLE_AUDIT_UPDATE = "admin.role.update"

DEFAULT_LIMIT = 25
MAX_LIMIT = 200

MAX_MAINTENANCE_MESSAGE_LEN = 2000
MAX_COMPOSIO_TOOL_LEN = 64
MAX_COMPOSIO_TOOLS = 200

# Roles an admin can assign through the CRM.  ``banned`` and ``user`` are
# intentionally excluded — those flow through ban/unban, not role flips.
ASSIGNABLE_ROLES: frozenset[str] = frozenset(
    {Role.ANALYST.value, Role.SUPPORT_ADMIN.value, Role.SUPER_ADMIN.value, Role.USER.value}
)


# ----------------------------------------------------------------- exceptions


class SystemSettingsError(Exception):
    """Base class for system settings failures."""


class InvalidSettingPayloadError(SystemSettingsError):
    """Caller supplied a malformed payload."""


class AdminRoleChangeError(SystemSettingsError):
    """Raised when an admin role mutation is refused (e.g. self-demote)."""


# ----------------------------------------------------------------- dataclasses


@dataclass(frozen=True)
class MaintenanceState:
    enabled: bool
    message: str | None
    updated_at: datetime | None
    updated_by: int | None


@dataclass(frozen=True)
class ComposioState:
    enabled_tools: list[str]
    config: dict[str, Any]
    updated_at: datetime | None
    updated_by: int | None


@dataclass(frozen=True)
class AdminUserRow:
    id: int
    telegram_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    role: str
    is_banned: bool
    last_login_at: datetime | None
    last_active_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class AdminUsersPage:
    items: list[AdminUserRow]
    total: int
    page: int
    limit: int
    has_more: bool


# ----------------------------------------------------------------- registry


SettingKey = Literal[
    "maintenance_mode",
    "rate_limits",
    "composio_config",
]

SETTINGS_REGISTRY: tuple[str, ...] = (
    MAINTENANCE_SETTING_KEY,
    RATE_LIMITS_KEY,
    COMPOSIO_SETTING_KEY,
)


# ----------------------------------------------------------------- helpers


async def _get_setting_row(session: AsyncSession, key: str) -> AdminSetting | None:
    stmt = select(AdminSetting).where(AdminSetting.setting_key == key)
    return (await session.execute(stmt)).scalar_one_or_none()


async def _upsert_setting(
    session: AsyncSession,
    *,
    key: str,
    value: dict[str, Any],
    admin: User,
) -> AdminSetting:
    row = await _get_setting_row(session, key)
    if row is None:
        row = AdminSetting(
            setting_key=key,
            setting_value=value,
            updated_by=admin.id,
        )
        session.add(row)
    else:
        row.setting_value = value
        row.updated_by = admin.id
        row.updated_at = datetime.now(UTC)
    await session.flush()
    return row


def _audit(
    *,
    admin: User,
    action: str,
    payload: dict[str, Any] | None,
    ip_address: str | None,
    user_agent: str | None,
    target_user_id: int | None = None,
) -> AdminAuditLog:
    return AdminAuditLog(
        admin_id=admin.id,
        target_user_id=target_user_id,
        action=action[:64],
        payload=payload,
        ip_address=(ip_address or "")[:64] or None,
        user_agent=(user_agent or "")[:512] or None,
    )


# =============================================================== maintenance


def _coerce_maintenance(raw: Any) -> MaintenanceState:
    if not isinstance(raw, dict):
        return MaintenanceState(enabled=False, message=None, updated_at=None, updated_by=None)
    enabled = bool(raw.get("enabled"))
    message = raw.get("message")
    if isinstance(message, str):
        message = message.strip() or None
    else:
        message = None
    return MaintenanceState(
        enabled=enabled,
        message=message,
        updated_at=None,
        updated_by=None,
    )


async def get_maintenance_state(session: AsyncSession) -> MaintenanceState:
    row = await _get_setting_row(session, MAINTENANCE_SETTING_KEY)
    if row is None:
        return MaintenanceState(enabled=False, message=None, updated_at=None, updated_by=None)
    state = _coerce_maintenance(row.setting_value)
    return MaintenanceState(
        enabled=state.enabled,
        message=state.message,
        updated_at=row.updated_at,
        updated_by=row.updated_by,
    )


async def update_maintenance_state(
    session: AsyncSession,
    *,
    admin: User,
    enabled: bool,
    message: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> MaintenanceState:
    cleaned_message: str | None = None
    if message is not None:
        cleaned = (message or "").strip()
        if len(cleaned) > MAX_MAINTENANCE_MESSAGE_LEN:
            raise InvalidSettingPayloadError(
                f"message exceeds {MAX_MAINTENANCE_MESSAGE_LEN} characters"
            )
        cleaned_message = cleaned or None

    before = await get_maintenance_state(session)
    payload: dict[str, Any] = {"enabled": bool(enabled), "message": cleaned_message}
    row = await _upsert_setting(
        session,
        key=MAINTENANCE_SETTING_KEY,
        value=payload,
        admin=admin,
    )

    session.add(
        _audit(
            admin=admin,
            action=MAINTENANCE_AUDIT_UPDATE,
            payload={
                "before": {"enabled": before.enabled, "message": before.message},
                "after": payload,
            },
            ip_address=ip_address,
            user_agent=user_agent,
        )
    )
    await session.flush()
    return MaintenanceState(
        enabled=payload["enabled"],
        message=payload["message"],
        updated_at=row.updated_at,
        updated_by=row.updated_by,
    )


# =============================================================== rate limits


def _serialise_rule(rule: Any) -> dict[str, int]:
    return {"limit": int(rule.limit), "window_seconds": int(rule.window_seconds)}


async def get_rate_limits(session: AsyncSession) -> dict[str, Any]:
    """Return the *effective* rate-limit catalog (defaults + overrides)."""
    row = await _get_setting_row(session, RATE_LIMITS_KEY)
    overrides = row.setting_value if row is not None else None
    merged = merge_overrides(DEFAULT_RATE_LIMITS, overrides)
    return {
        "plans": {
            plan: {action: _serialise_rule(rule) for action, rule in rules.items()}
            for plan, rules in merged.items()
        },
        "overrides": overrides or {},
        "defaults": {
            plan: {action: _serialise_rule(rule) for action, rule in rules.items()}
            for plan, rules in DEFAULT_RATE_LIMITS.items()
        },
        "updated_at": row.updated_at if row is not None else None,
        "updated_by": row.updated_by if row is not None else None,
    }


def _validate_rate_overrides(overrides: dict[str, Any] | None) -> dict[str, Any]:
    """Round-trip through :func:`merge_overrides` to validate shape."""
    if overrides is None:
        return {}
    if not isinstance(overrides, dict):
        raise InvalidSettingPayloadError("rate_limits overrides must be a mapping")
    # ``merge_overrides`` logs and ignores bad rules; we surface them as errors.
    for plan, plan_overrides in overrides.items():
        if not isinstance(plan_overrides, dict):
            raise InvalidSettingPayloadError(
                f"rate_limits[{plan!r}] must be a mapping"
            )
        for action, raw in plan_overrides.items():
            if not isinstance(raw, dict):
                raise InvalidSettingPayloadError(
                    f"rate_limits[{plan!r}][{action!r}] must be a mapping"
                )
            try:
                limit = int(raw.get("limit"))  # type: ignore[arg-type]
                window = int(raw.get("window_seconds"))  # type: ignore[arg-type]
            except (TypeError, ValueError) as exc:
                raise InvalidSettingPayloadError(
                    f"rate_limits[{plan!r}][{action!r}] requires int limit / window_seconds"
                ) from exc
            if limit <= 0 or window <= 0:
                raise InvalidSettingPayloadError(
                    f"rate_limits[{plan!r}][{action!r}] requires positive values"
                )
    return overrides


async def update_rate_limits(
    session: AsyncSession,
    *,
    admin: User,
    overrides: dict[str, Any] | None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    cleaned = _validate_rate_overrides(overrides)

    row = await _get_setting_row(session, RATE_LIMITS_KEY)
    before = row.setting_value if row is not None else None

    await _upsert_setting(
        session,
        key=RATE_LIMITS_KEY,
        value=cleaned,
        admin=admin,
    )
    session.add(
        _audit(
            admin=admin,
            action=RATE_LIMITS_AUDIT_UPDATE,
            payload={"before": before, "after": cleaned},
            ip_address=ip_address,
            user_agent=user_agent,
        )
    )
    await session.flush()
    return await get_rate_limits(session)


# ============================================================ composio config


def _coerce_composio(raw: Any) -> ComposioState:
    if not isinstance(raw, dict):
        return ComposioState(enabled_tools=[], config={}, updated_at=None, updated_by=None)
    tools = raw.get("enabled_tools") or []
    if not isinstance(tools, list):
        tools = []
    cleaned_tools = [str(t).strip() for t in tools if isinstance(t, str | int) and str(t).strip()]
    cleaned_tools = list(dict.fromkeys(cleaned_tools))  # dedupe, preserve order
    config = raw.get("config")
    if not isinstance(config, dict):
        config = {}
    return ComposioState(
        enabled_tools=cleaned_tools,
        config=config,
        updated_at=None,
        updated_by=None,
    )


async def get_composio_state(session: AsyncSession) -> ComposioState:
    row = await _get_setting_row(session, COMPOSIO_SETTING_KEY)
    if row is None:
        return ComposioState(enabled_tools=[], config={}, updated_at=None, updated_by=None)
    state = _coerce_composio(row.setting_value)
    return ComposioState(
        enabled_tools=state.enabled_tools,
        config=state.config,
        updated_at=row.updated_at,
        updated_by=row.updated_by,
    )


def _validate_composio(enabled_tools: list[str], config: dict[str, Any] | None) -> tuple[list[str], dict[str, Any]]:
    if not isinstance(enabled_tools, list):
        raise InvalidSettingPayloadError("enabled_tools must be a list of strings")
    cleaned: list[str] = []
    seen: set[str] = set()
    for tool in enabled_tools:
        if not isinstance(tool, str):
            raise InvalidSettingPayloadError("enabled_tools must contain only strings")
        slug = tool.strip()
        if not slug:
            continue
        if len(slug) > MAX_COMPOSIO_TOOL_LEN:
            raise InvalidSettingPayloadError(
                f"tool slug exceeds {MAX_COMPOSIO_TOOL_LEN} characters"
            )
        if slug in seen:
            continue
        seen.add(slug)
        cleaned.append(slug)
    if len(cleaned) > MAX_COMPOSIO_TOOLS:
        raise InvalidSettingPayloadError(
            f"enabled_tools exceeds {MAX_COMPOSIO_TOOLS} entries"
        )
    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise InvalidSettingPayloadError("config must be a mapping")
    return cleaned, config


async def update_composio_state(
    session: AsyncSession,
    *,
    admin: User,
    enabled_tools: list[str],
    config: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> ComposioState:
    cleaned_tools, cleaned_config = _validate_composio(enabled_tools, config)

    before = await get_composio_state(session)
    payload: dict[str, Any] = {
        "enabled_tools": cleaned_tools,
        "config": cleaned_config,
    }
    row = await _upsert_setting(
        session,
        key=COMPOSIO_SETTING_KEY,
        value=payload,
        admin=admin,
    )
    session.add(
        _audit(
            admin=admin,
            action=COMPOSIO_AUDIT_UPDATE,
            payload={
                "before": {
                    "enabled_tools": before.enabled_tools,
                    "config": before.config,
                },
                "after": payload,
            },
            ip_address=ip_address,
            user_agent=user_agent,
        )
    )
    await session.flush()
    return ComposioState(
        enabled_tools=cleaned_tools,
        config=cleaned_config,
        updated_at=row.updated_at,
        updated_by=row.updated_by,
    )


# =========================================================== admin users mgmt


ADMIN_ROLES_FILTER: frozenset[str] = frozenset(
    {Role.ANALYST.value, Role.SUPPORT_ADMIN.value, Role.SUPER_ADMIN.value}
)


def _user_to_row(user: User) -> AdminUserRow:
    return AdminUserRow(
        id=user.id,
        telegram_id=user.telegram_id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        role=user.role,
        is_banned=bool(user.is_banned),
        last_login_at=user.last_login_at,
        last_active_at=user.last_active_at,
        created_at=user.created_at,
    )


async def list_admin_users(
    session: AsyncSession,
    *,
    role: str | None = None,
    page: int = 1,
    limit: int = DEFAULT_LIMIT,
) -> AdminUsersPage:
    """Return users holding any admin-tier role (``analyst`` or above)."""
    page = max(int(page or 1), 1)
    limit = max(min(int(limit or DEFAULT_LIMIT), MAX_LIMIT), 1)
    offset = (page - 1) * limit

    role_filter: tuple[str, ...]
    if role:
        if role not in ADMIN_ROLES_FILTER:
            raise InvalidSettingPayloadError(f"unsupported role={role!r}")
        role_filter = (role,)
    else:
        role_filter = tuple(ADMIN_ROLES_FILTER)

    count_stmt = (
        select(func.count())
        .select_from(User)
        .where(User.role.in_(role_filter))
    )
    rows_stmt = (
        select(User)
        .where(User.role.in_(role_filter))
        .order_by(User.role.asc(), User.created_at.desc(), User.id.desc())
        .offset(offset)
        .limit(limit)
    )
    total = int((await session.execute(count_stmt)).scalar_one())
    rows = list((await session.execute(rows_stmt)).scalars().all())
    items = [_user_to_row(u) for u in rows]
    return AdminUsersPage(
        items=items,
        total=total,
        page=page,
        limit=limit,
        has_more=(page * limit) < total,
    )


async def _count_super_admins(session: AsyncSession) -> int:
    stmt = (
        select(func.count())
        .select_from(User)
        .where(User.role == Role.SUPER_ADMIN.value)
    )
    return int((await session.execute(stmt)).scalar_one())


async def update_admin_role(
    session: AsyncSession,
    *,
    admin: User,
    target_user_id: int,
    role: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> AdminUserRow:
    """Change the role of ``target_user_id``.

    Only ``super_admin`` may change roles (the API layer enforces this).
    The service refuses to demote the last remaining super-admin so the
    system always has at least one root operator.
    """
    if role not in ASSIGNABLE_ROLES:
        raise InvalidSettingPayloadError(f"unsupported role={role!r}")

    target = await session.get(User, target_user_id)
    if target is None:
        raise AdminRoleChangeError(f"user {target_user_id} not found")

    previous_role = target.role
    if previous_role == role:
        return _user_to_row(target)

    # Last-super-admin safety rail.
    if previous_role == Role.SUPER_ADMIN.value and role != Role.SUPER_ADMIN.value:
        remaining = await _count_super_admins(session)
        if remaining <= 1:
            raise AdminRoleChangeError("cannot demote the last super_admin")

    target.role = role
    await session.flush()

    session.add(
        _audit(
            admin=admin,
            action=ADMIN_ROLE_AUDIT_UPDATE,
            payload={
                "user_id": target.id,
                "before": previous_role,
                "after": role,
            },
            ip_address=ip_address,
            user_agent=user_agent,
            target_user_id=target.id,
        )
    )
    await session.flush()
    logger.info(
        "admin.role.updated",
        admin_id=admin.id,
        target_user_id=target.id,
        before=previous_role,
        after=role,
    )
    return _user_to_row(target)


# Helper used by API layer to know whether the caller can mutate admin roles.
def can_manage_admin_roles(role: str) -> bool:
    return Role.coerce(role) is Role.SUPER_ADMIN


__all__ = [
    "ADMIN_ROLE_AUDIT_UPDATE",
    "ADMIN_ROLES_FILTER",
    "ASSIGNABLE_ROLES",
    "AdminRoleChangeError",
    "AdminUserRow",
    "AdminUsersPage",
    "COMPOSIO_AUDIT_UPDATE",
    "COMPOSIO_SETTING_KEY",
    "ComposioState",
    "InvalidSettingPayloadError",
    "MAINTENANCE_AUDIT_UPDATE",
    "MAINTENANCE_SETTING_KEY",
    "MaintenanceState",
    "RATE_LIMITS_AUDIT_UPDATE",
    "RATE_LIMITS_KEY",
    "SETTINGS_REGISTRY",
    "SystemSettingsError",
    "can_manage_admin_roles",
    "get_composio_state",
    "get_maintenance_state",
    "get_rate_limits",
    "list_admin_users",
    "update_admin_role",
    "update_composio_state",
    "update_maintenance_state",
    "update_rate_limits",
]
