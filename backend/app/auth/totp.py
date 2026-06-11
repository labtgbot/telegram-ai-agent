"""TOTP (RFC 6238) helpers used for super-admin 2FA.

Wraps :mod:`pyotp` with sensible defaults (30-second steps, ``valid_window``
of one period to tolerate clock skew).
"""
from __future__ import annotations

import hmac
import time
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
    if now is None:
        return verify_totp_timecode(secret, code, valid_window=valid_window) is not None
    return verify_totp_timecode(secret, code, valid_window=valid_window, now=now) is not None


def verify_totp_timecode(
    secret: str,
    code: str,
    *,
    valid_window: int = DEFAULT_VALID_WINDOW,
    now: float | None = None,
) -> int | None:
    """Return the accepted TOTP timestep, or ``None`` when invalid."""
    if not secret or not code or valid_window < 0:
        return None
    candidate = code.strip()
    if not candidate.isdigit():
        return None

    timestamp = time.time() if now is None else now
    current_timecode = int(timestamp // DEFAULT_INTERVAL)
    totp = pyotp.TOTP(secret, interval=DEFAULT_INTERVAL, digits=DEFAULT_DIGITS)
    for offset in range(-valid_window, valid_window + 1):
        timecode = current_timecode + offset
        if timecode < 0:
            continue
        expected = totp.at(timecode * DEFAULT_INTERVAL)
        if hmac.compare_digest(expected, candidate):
            return timecode
    return None


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
