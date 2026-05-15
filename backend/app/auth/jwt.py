"""Admin JWT helpers (access + refresh tokens).

Tokens are JWS-compact (HS256 by default).  Two distinct token types are
issued so that the refresh token cannot be used to authenticate API calls
directly:

* ``access`` — short-lived (15 minutes), used as ``Authorization: Bearer``.
* ``refresh`` — long-lived (7 days), used only against
  ``POST /auth/admin/refresh``.

The payload includes:

* ``sub`` — user id (string).
* ``role`` — RBAC role at issue time.
* ``type`` — ``access`` or ``refresh``.
* ``iat`` / ``exp`` / ``jti`` — standard claims.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from time import time
from typing import Any, Literal

from jose import JWTError, jwt
from jose.exceptions import ExpiredSignatureError

TokenType = Literal["access", "refresh"]


class InvalidTokenError(Exception):
    """Raised when a JWT fails signature, structure, or type checks."""


class TokenExpiredError(InvalidTokenError):
    """Raised when the JWT signature is valid but ``exp`` has passed."""


@dataclass(frozen=True)
class TokenClaims:
    sub: str
    role: str
    type: TokenType
    iat: int
    exp: int
    jti: str


def _encode(
    *,
    subject: str | int,
    role: str,
    token_type: TokenType,
    ttl_seconds: int,
    secret: str,
    algorithm: str,
    now: float | None = None,
) -> str:
    issued_at = int(now if now is not None else time())
    payload: dict[str, Any] = {
        "sub": str(subject),
        "role": role,
        "type": token_type,
        "iat": issued_at,
        "exp": issued_at + ttl_seconds,
        "jti": secrets.token_urlsafe(16),
    }
    return jwt.encode(payload, secret, algorithm=algorithm)


def create_access_token(
    *,
    subject: str | int,
    role: str,
    secret: str,
    algorithm: str = "HS256",
    ttl_seconds: int = 15 * 60,
    now: float | None = None,
) -> str:
    return _encode(
        subject=subject,
        role=role,
        token_type="access",
        ttl_seconds=ttl_seconds,
        secret=secret,
        algorithm=algorithm,
        now=now,
    )


def create_refresh_token(
    *,
    subject: str | int,
    role: str,
    secret: str,
    algorithm: str = "HS256",
    ttl_seconds: int = 7 * 24 * 60 * 60,
    now: float | None = None,
) -> str:
    return _encode(
        subject=subject,
        role=role,
        token_type="refresh",
        ttl_seconds=ttl_seconds,
        secret=secret,
        algorithm=algorithm,
        now=now,
    )


def decode_token(
    token: str,
    *,
    secret: str,
    algorithm: str = "HS256",
    expected_type: TokenType | None = None,
) -> TokenClaims:
    """Validate and return the claims encoded in ``token``.

    Raises:
        TokenExpiredError: Signature valid but ``exp`` has passed.
        InvalidTokenError: Any other validation failure (bad signature,
            malformed JWT, type mismatch, missing claim).
    """
    try:
        payload = jwt.decode(token, secret, algorithms=[algorithm])
    except ExpiredSignatureError as exc:
        raise TokenExpiredError("token expired") from exc
    except JWTError as exc:
        raise InvalidTokenError(str(exc)) from exc

    try:
        claims = TokenClaims(
            sub=str(payload["sub"]),
            role=str(payload["role"]),
            type=payload["type"],
            iat=int(payload["iat"]),
            exp=int(payload["exp"]),
            jti=str(payload["jti"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidTokenError("missing or malformed claim") from exc

    if claims.type not in {"access", "refresh"}:
        raise InvalidTokenError(f"unknown token type: {claims.type!r}")

    if expected_type is not None and claims.type != expected_type:
        raise InvalidTokenError(
            f"expected {expected_type!r} token, got {claims.type!r}"
        )

    return claims
