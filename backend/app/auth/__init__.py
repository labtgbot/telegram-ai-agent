"""Authentication & authorization primitives.

Public surface:

* :mod:`app.auth.telegram` — HMAC verification of Telegram WebApp ``initData``.
* :mod:`app.auth.jwt` — admin JWT access/refresh token helpers.
* :mod:`app.auth.totp` — RFC 6238 TOTP helpers (2FA for super-admins).
* :mod:`app.auth.rbac` — :class:`Role` enum and :func:`require_role` dependency.
"""
from app.auth.jwt import (
    InvalidTokenError,
    TokenExpiredError,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.auth.rbac import Role, require_role
from app.auth.telegram import (
    InitDataExpiredError,
    InitDataInvalidError,
    TelegramUser,
    verify_init_data,
)
from app.auth.totp import generate_totp_secret, provisioning_uri, verify_totp

__all__ = [
    "InitDataExpiredError",
    "InitDataInvalidError",
    "InvalidTokenError",
    "Role",
    "TelegramUser",
    "TokenExpiredError",
    "create_access_token",
    "create_refresh_token",
    "decode_token",
    "generate_totp_secret",
    "provisioning_uri",
    "require_role",
    "verify_init_data",
    "verify_totp",
]
