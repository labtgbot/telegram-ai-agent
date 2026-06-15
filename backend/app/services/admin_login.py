"""Admin login lifecycle (one-time code + TOTP) backed by Redis.

The flow has three steps:

1. ``request_admin_login`` — admin posts their ``telegram_id``.  We mint a
   numeric code, store the (salted) hash in Redis under
   ``admin:login:<telegram_id>``, and (in production) push it to the admin
   via the bot.  In development environments the code is also returned in
   the response so e2e tests can complete without a bot.
2. ``verify_admin_login`` — admin posts ``telegram_id`` + ``code`` (and the
   ``totp_code`` if 2FA is enabled).  We compare the hash in constant time,
   track failed attempts independently from code re-issuance, delete the key,
   and let the caller mint JWTs.
3. Subsequent JWT refresh uses :func:`app.auth.jwt.decode_token` directly.

Storing the salted SHA-256 hash (rather than the code itself) means a Redis
dump never reveals the live code.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Any, Protocol


class LoginCodeError(Exception):
    """Base class for admin-login failures (used by API layer)."""


class LoginCodeMissingError(LoginCodeError):
    """No outstanding code for this telegram_id (or it expired)."""


class LoginCodeInvalidError(LoginCodeError):
    """The supplied code did not match."""


class LoginCodeAttemptsExceededError(LoginCodeError):
    """Too many wrong codes; the session has been invalidated."""


@dataclass(frozen=True)
class AdminLoginCode:
    """Material returned to the bot to deliver the code to the admin.

    ``code`` is the value the admin types back in.  ``ttl_seconds`` is the
    remaining validity window.
    """

    code: str
    ttl_seconds: int


class _AsyncRedisLike(Protocol):
    """Structural subset of ``redis.asyncio.Redis`` used by this module.

    Loosely typed (``Any``) so the real client *and* simple in-memory test
    doubles both satisfy it.
    """

    async def set(self, key: Any, value: Any, *, ex: Any = ..., nx: Any = ...) -> Any: ...
    async def get(self, key: Any) -> Any: ...
    async def delete(self, *keys: Any) -> Any: ...
    async def incr(self, key: Any) -> Any: ...
    async def expire(self, key: Any, seconds: Any) -> Any: ...


def generate_numeric_login_code(length: int) -> str:
    if length < 4 or length > 10:
        raise ValueError("login code length must be between 4 and 10")
    upper = 10**length
    n = secrets.randbelow(upper)
    return str(n).zfill(length)


def _generate_numeric_code(length: int) -> str:
    return generate_numeric_login_code(length)


def _hash_code(code: str, *, salt: str) -> str:
    payload = f"{salt}:{code}".encode()
    return hashlib.sha256(payload).hexdigest()


def _key(prefix: str, telegram_id: int) -> str:
    return f"admin:login:{prefix}:{telegram_id}"


async def request_admin_login(
    redis: Any,
    *,
    telegram_id: int,
    secret: str,
    ttl_seconds: int,
    code_length: int,
) -> AdminLoginCode:
    """Mint a new one-time code, overwriting any previous outstanding one."""
    code = generate_numeric_login_code(code_length)
    digest = _hash_code(code, salt=secret)
    await redis.set(_key("hash", telegram_id), digest, ex=ttl_seconds)
    return AdminLoginCode(code=code, ttl_seconds=ttl_seconds)


async def verify_admin_login(
    redis: Any,
    *,
    telegram_id: int,
    code: str,
    secret: str,
    max_attempts: int,
    ttl_seconds: int,
) -> None:
    """Verify a code; on success the stored hash is deleted.

    Raises:
        LoginCodeMissingError: No outstanding code for ``telegram_id``.
        LoginCodeAttemptsExceededError: Too many wrong attempts.
        LoginCodeInvalidError: Code did not match.
    """
    if not code or not code.strip().isdigit():
        raise LoginCodeInvalidError("code must be numeric")

    stored = await redis.get(_key("hash", telegram_id))
    if stored is None:
        raise LoginCodeMissingError("no outstanding code")

    stored_str = stored.decode() if isinstance(stored, (bytes, bytearray)) else stored
    attempts_key = _key("attempts", telegram_id)
    attempts = await redis.incr(attempts_key)
    if attempts == 1:
        await redis.expire(attempts_key, ttl_seconds)
    if attempts > max_attempts:
        await redis.delete(_key("hash", telegram_id))
        raise LoginCodeAttemptsExceededError("too many attempts")

    expected = _hash_code(code.strip(), salt=secret)
    if not hmac.compare_digest(stored_str, expected):
        raise LoginCodeInvalidError("code mismatch")

    await redis.delete(_key("hash", telegram_id), attempts_key)
