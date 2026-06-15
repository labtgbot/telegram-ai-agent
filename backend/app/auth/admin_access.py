"""Minimum roles for backend admin API areas.

Keep this matrix aligned with ``admin-dashboard/middleware.ts`` so direct
backend calls cannot bypass dashboard page gates.
"""
from __future__ import annotations

from typing import Final

from app.auth.rbac import Role

ADMIN_ANALYTICS_MIN_ROLE: Final[Role] = Role.ANALYST
ADMIN_ANALYTICS_EXPORT_MIN_ROLE: Final[Role] = Role.SUPPORT_ADMIN
ADMIN_BROADCASTS_MIN_ROLE: Final[Role] = Role.SUPPORT_ADMIN
ADMIN_CONTENT_MIN_ROLE: Final[Role] = Role.SUPPORT_ADMIN
ADMIN_PRICING_MIN_ROLE: Final[Role] = Role.SUPER_ADMIN
ADMIN_SYSTEM_MIN_ROLE: Final[Role] = Role.SUPER_ADMIN
ADMIN_USERS_MIN_ROLE: Final[Role] = Role.SUPPORT_ADMIN

ADMIN_API_MIN_ROLES: Final[dict[str, Role]] = {
    "admin.analytics": ADMIN_ANALYTICS_MIN_ROLE,
    "admin.analytics.export": ADMIN_ANALYTICS_EXPORT_MIN_ROLE,
    "admin.broadcasts": ADMIN_BROADCASTS_MIN_ROLE,
    "admin.content": ADMIN_CONTENT_MIN_ROLE,
    "admin.pricing": ADMIN_PRICING_MIN_ROLE,
    "admin.system": ADMIN_SYSTEM_MIN_ROLE,
    "admin.users": ADMIN_USERS_MIN_ROLE,
}

__all__ = [
    "ADMIN_ANALYTICS_EXPORT_MIN_ROLE",
    "ADMIN_ANALYTICS_MIN_ROLE",
    "ADMIN_API_MIN_ROLES",
    "ADMIN_BROADCASTS_MIN_ROLE",
    "ADMIN_CONTENT_MIN_ROLE",
    "ADMIN_PRICING_MIN_ROLE",
    "ADMIN_SYSTEM_MIN_ROLE",
    "ADMIN_USERS_MIN_ROLE",
]
