"""TOTP (RFC 6238) helpers used for super-admin 2FA.

Wraps :mod:`pyotp` with sensible defaults (30-second steps, ``valid_window``
of one period to tolerate clock skew).
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

import pyotp

DEFAULT_INTERVAL: Final[int] = 30
DEFAULT_DIGITS: Final[int] = 6
DEFAULT_VALID_WINDOW: Final[int] = 1


def generate_totp_secret() -> str:
    """Return a fresh base32-encoded TOTP secret."""
    return pyotp.random_base32()


def verify_totp(
    secret: str,
    code: str,
    *,
    valid_window: int = DEFAULT_VALID_WINDOW,
    now: float | None = None,
) -> bool:
    """Return ``True`` if ``code`` is the current TOTP for ``secret``.

    ``valid_window`` allows codes that are one period stale in either
    direction (default ±30s).
    """
    if not secret or not code:
        return False
    candidate = code.strip()
    if not candidate.isdigit():
        return False
    totp = pyotp.TOTP(secret, interval=DEFAULT_INTERVAL, digits=DEFAULT_DIGITS)
    if now is None:
        return totp.verify(candidate, valid_window=valid_window)
    for_time = datetime.fromtimestamp(now, tz=UTC)
    return totp.verify(candidate, valid_window=valid_window, for_time=for_time)


def provisioning_uri(
    secret: str,
    *,
    account_name: str,
    issuer: str,
) -> str:
    """Build an ``otpauth://`` URI for QR-code provisioning."""
    return pyotp.TOTP(
        secret, interval=DEFAULT_INTERVAL, digits=DEFAULT_DIGITS
    ).provisioning_uri(name=account_name, issuer_name=issuer)
