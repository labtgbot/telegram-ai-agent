"""Admin system-settings endpoints (Phase 3, issue #29).

Endpoints under ``/admin/system``:

* ``GET  /admin/system/maintenance`` — current maintenance toggle.
* ``PUT  /admin/system/maintenance`` — enable / disable maintenance mode.
* ``GET  /admin/system/rate-limits`` — effective rate-limit catalog.
* ``PUT  /admin/system/rate-limits`` — replace the override map.
* ``GET  /admin/system/composio`` — composio integration config.
* ``PUT  /admin/system/composio`` — update enabled tool slugs + config.
* ``GET  /admin/system/admins`` — list users with admin-tier roles.
* ``PUT  /admin/system/admins/{user_id}/role`` — change a user's role.

Reads are open to ``analyst`` and above.  Maintenance/composio writes
require ``support_admin``; rate-limit and admin-role writes are gated to
``super_admin`` because they directly shape billing and access control.
Every mutation writes an :class:`AdminAuditLog` row through the service
layer in the same transaction.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    status,
)
from pydantic import BaseModel, Field

from app.auth.dependencies import SessionDep, get_current_admin
from app.auth.rbac import Role, require_role
from app.core.logging import get_logger
from app.models.user import User
from app.services.admin_system import (
    ASSIGNABLE_ROLES,
    AdminRoleChangeError,
    AdminUserRow,
    ComposioState,
    InvalidSettingPayloadError,
    MaintenanceState,
    get_composio_state,
    get_maintenance_state,
    get_rate_limits,
    list_admin_users,
    update_admin_role,
    update_composio_state,
    update_maintenance_state,
    update_rate_limits,
)

router = APIRouter(prefix="/admin/system", tags=["admin-system"])
logger = get_logger(__name__)


# ----------------------------------------------------------------- helpers


def _request_meta(request: Request) -> tuple[str | None, str | None]:
    ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (
        request.client.host if request.client else None
    )
    return ip or None, request.headers.get("user-agent")


async def _commit_or_500(session: Any) -> None:
    try:
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        logger.exception("admin_system.commit_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="commit_failed",
        ) from exc


def _payload_error(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=str(exc),
    )


# ================================================================ maintenance


class MaintenanceResponse(BaseModel):
    enabled: bool
    message: str | None = None
    updated_at: datetime | None = None
    updated_by: int | None = None

    @classmethod
    def from_state(cls, state: MaintenanceState) -> MaintenanceResponse:
        return cls(
            enabled=state.enabled,
            message=state.message,
            updated_at=state.updated_at,
            updated_by=state.updated_by,
        )


class MaintenanceUpdateRequest(BaseModel):
    enabled: bool
    message: str | None = Field(default=None, max_length=2000)


@router.get(
    "/maintenance",
    response_model=MaintenanceResponse,
    summary="Get maintenance-mode state",
)
async def get_maintenance_endpoint(
    session: SessionDep,
    admin: Annotated[User, Depends(get_current_admin)],
) -> MaintenanceResponse:
    state = await get_maintenance_state(session)
    return MaintenanceResponse.from_state(state)


@router.put(
    "/maintenance",
    response_model=MaintenanceResponse,
    summary="Toggle maintenance mode",
)
async def update_maintenance_endpoint(
    payload: MaintenanceUpdateRequest,
    request: Request,
    session: SessionDep,
    admin: Annotated[User, Depends(require_role(Role.SUPPORT_ADMIN))],
) -> MaintenanceResponse:
    ip, ua = _request_meta(request)
    try:
        state = await update_maintenance_state(
            session,
            admin=admin,
            enabled=payload.enabled,
            message=payload.message,
            ip_address=ip,
            user_agent=ua,
        )
    except InvalidSettingPayloadError as exc:
        raise _payload_error(exc) from exc
    await _commit_or_500(session)
    return MaintenanceResponse.from_state(state)


# ================================================================ rate limits


class RateLimitsResponse(BaseModel):
    plans: dict[str, dict[str, dict[str, int]]]
    overrides: dict[str, Any]
    defaults: dict[str, dict[str, dict[str, int]]]
    updated_at: datetime | None = None
    updated_by: int | None = None


class RateLimitsUpdateRequest(BaseModel):
    overrides: dict[str, dict[str, dict[str, int]]] | None = None


@router.get(
    "/rate-limits",
    response_model=RateLimitsResponse,
    summary="Get the effective rate-limit catalog",
)
async def get_rate_limits_endpoint(
    session: SessionDep,
    admin: Annotated[User, Depends(get_current_admin)],
) -> RateLimitsResponse:
    data = await get_rate_limits(session)
    return RateLimitsResponse(**data)


@router.put(
    "/rate-limits",
    response_model=RateLimitsResponse,
    summary="Replace the rate-limit override map",
)
async def update_rate_limits_endpoint(
    payload: RateLimitsUpdateRequest,
    request: Request,
    session: SessionDep,
    admin: Annotated[User, Depends(require_role(Role.SUPER_ADMIN))],
) -> RateLimitsResponse:
    ip, ua = _request_meta(request)
    try:
        data = await update_rate_limits(
            session,
            admin=admin,
            overrides=payload.overrides,
            ip_address=ip,
            user_agent=ua,
        )
    except InvalidSettingPayloadError as exc:
        raise _payload_error(exc) from exc
    await _commit_or_500(session)
    return RateLimitsResponse(**data)


# =============================================================== composio


class ComposioResponse(BaseModel):
    enabled_tools: list[str]
    config: dict[str, Any]
    updated_at: datetime | None = None
    updated_by: int | None = None

    @classmethod
    def from_state(cls, state: ComposioState) -> ComposioResponse:
        return cls(
            enabled_tools=list(state.enabled_tools),
            config=dict(state.config),
            updated_at=state.updated_at,
            updated_by=state.updated_by,
        )


class ComposioUpdateRequest(BaseModel):
    enabled_tools: list[str] = Field(default_factory=list, max_length=200)
    config: dict[str, Any] | None = None


@router.get(
    "/composio",
    response_model=ComposioResponse,
    summary="Get composio integration config",
)
async def get_composio_endpoint(
    session: SessionDep,
    admin: Annotated[User, Depends(get_current_admin)],
) -> ComposioResponse:
    state = await get_composio_state(session)
    return ComposioResponse.from_state(state)


@router.put(
    "/composio",
    response_model=ComposioResponse,
    summary="Update enabled composio tools and config",
)
async def update_composio_endpoint(
    payload: ComposioUpdateRequest,
    request: Request,
    session: SessionDep,
    admin: Annotated[User, Depends(require_role(Role.SUPPORT_ADMIN))],
) -> ComposioResponse:
    ip, ua = _request_meta(request)
    try:
        state = await update_composio_state(
            session,
            admin=admin,
            enabled_tools=payload.enabled_tools,
            config=payload.config,
            ip_address=ip,
            user_agent=ua,
        )
    except InvalidSettingPayloadError as exc:
        raise _payload_error(exc) from exc
    await _commit_or_500(session)
    return ComposioResponse.from_state(state)


# ============================================================= admin users


class AdminUserResponse(BaseModel):
    id: int
    telegram_id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    role: str
    is_banned: bool
    last_login_at: datetime | None = None
    last_active_at: datetime | None = None
    created_at: datetime

    @classmethod
    def from_row(cls, row: AdminUserRow) -> AdminUserResponse:
        return cls(
            id=row.id,
            telegram_id=row.telegram_id,
            username=row.username,
            first_name=row.first_name,
            last_name=row.last_name,
            role=row.role,
            is_banned=row.is_banned,
            last_login_at=row.last_login_at,
            last_active_at=row.last_active_at,
            created_at=row.created_at,
        )


class AdminUserListResponse(BaseModel):
    items: list[AdminUserResponse]
    total: int
    page: int
    limit: int
    has_more: bool
    assignable_roles: list[str]


class AdminRoleUpdateRequest(BaseModel):
    role: str = Field(..., min_length=1, max_length=32)


@router.get(
    "/admins",
    response_model=AdminUserListResponse,
    summary="List admin-tier users",
)
async def list_admins_endpoint(
    session: SessionDep,
    admin: Annotated[User, Depends(get_current_admin)],
    role: Annotated[str | None, Query(max_length=32)] = None,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
) -> AdminUserListResponse:
    try:
        result = await list_admin_users(session, role=role, page=page, limit=limit)
    except InvalidSettingPayloadError as exc:
        raise _payload_error(exc) from exc
    return AdminUserListResponse(
        items=[AdminUserResponse.from_row(r) for r in result.items],
        total=result.total,
        page=result.page,
        limit=result.limit,
        has_more=result.has_more,
        assignable_roles=sorted(ASSIGNABLE_ROLES),
    )


@router.put(
    "/admins/{user_id}/role",
    response_model=AdminUserResponse,
    summary="Change a user's role (super_admin only)",
)
async def update_admin_role_endpoint(
    user_id: int,
    payload: AdminRoleUpdateRequest,
    request: Request,
    session: SessionDep,
    admin: Annotated[User, Depends(require_role(Role.SUPER_ADMIN))],
) -> AdminUserResponse:
    ip, ua = _request_meta(request)
    try:
        row = await update_admin_role(
            session,
            admin=admin,
            target_user_id=user_id,
            role=payload.role,
            ip_address=ip,
            user_agent=ua,
        )
    except InvalidSettingPayloadError as exc:
        raise _payload_error(exc) from exc
    except AdminRoleChangeError as exc:
        message = str(exc)
        if "not found" in message:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="user_not_found",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=message,
        ) from exc
    await _commit_or_500(session)
    return AdminUserResponse.from_row(row)


__all__ = [
    "AdminRoleUpdateRequest",
    "AdminUserListResponse",
    "AdminUserResponse",
    "ComposioResponse",
    "ComposioUpdateRequest",
    "MaintenanceResponse",
    "MaintenanceUpdateRequest",
    "RateLimitsResponse",
    "RateLimitsUpdateRequest",
    "router",
]
