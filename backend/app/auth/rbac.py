"""Role-based access control primitives.

The :class:`Role` enum mirrors ``docs/SECURITY.md``.  :func:`require_role`
is a FastAPI dependency factory: it composes with
:func:`app.auth.dependencies.get_current_admin` so calling it directly works
as both a function-decorator-like dependency and as an explicit
``Depends(require_role("super_admin"))``.

A role is *granted* if it is at least as privileged as the requested one,
where privilege is ranked roughly as::

    super_admin > support_admin > analyst > user > banned
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from enum import StrEnum
from typing import Any

from fastapi import Depends, HTTPException, status


class Role(StrEnum):
    """RBAC roles.  Values match the ``users.role`` column."""

    SUPER_ADMIN = "super_admin"
    SUPPORT_ADMIN = "support_admin"
    ANALYST = "analyst"
    USER = "user"
    BANNED = "banned"

    @classmethod
    def coerce(cls, value: str | Role | None) -> Role:
        if isinstance(value, cls):
            return value
        if not value:
            return cls.USER
        try:
            return cls(value)
        except ValueError:
            return cls.USER


_RANK: dict[Role, int] = {
    Role.BANNED: -1,
    Role.USER: 0,
    Role.ANALYST: 1,
    Role.SUPPORT_ADMIN: 2,
    Role.SUPER_ADMIN: 3,
}


def role_satisfies(actual: Role, required: Role) -> bool:
    """Return ``True`` when ``actual`` is at least as privileged as ``required``."""
    if actual is Role.BANNED:
        return False
    return _RANK[actual] >= _RANK[required]


def require_role(
    *allowed: str | Role,
) -> Callable[..., Any]:
    """FastAPI dependency factory enforcing one of ``allowed`` roles.

    Example::

        @router.get(
            "/admin/users",
            dependencies=[Depends(require_role("super_admin", "support_admin"))],
        )
        async def list_users(): ...

    Or as a parameter dependency to receive the resolved admin::

        async def handler(admin = Depends(require_role("super_admin"))): ...

    The check is "at least one of ``allowed`` is satisfied" — passing
    ``"support_admin"`` admits both ``support_admin`` and ``super_admin``.
    """
    if not allowed:
        raise ValueError("require_role: at least one role must be specified")
    required_roles = tuple(Role.coerce(r) for r in allowed)

    # Local import to avoid a circular dependency: dependencies imports rbac.
    from app.auth.dependencies import get_current_admin

    async def _checker(admin: Any = Depends(get_current_admin)) -> Any:  # noqa: B008
        actual = Role.coerce(getattr(admin, "role", None))
        if not any(role_satisfies(actual, req) for req in required_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="insufficient_role",
            )
        return admin

    return _checker


def any_role(values: Iterable[str | Role]) -> tuple[Role, ...]:
    """Coerce an iterable of role names/enums into a tuple of ``Role``."""
    return tuple(Role.coerce(v) for v in values)
