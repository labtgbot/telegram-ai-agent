"""Telegram WebApp ``initData`` verification.

Implements the HMAC-SHA256 procedure documented at
<https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app>:

1. Parse the ``initData`` query string.
2. Pop the ``hash`` field.
3. Build a "data-check-string": ``\\n``-joined ``key=value`` pairs sorted
   alphabetically by key.
4. ``secret_key = HMAC_SHA256(bot_token, key="WebAppData")``.
5. Expected hash = ``HMAC_SHA256(data_check_string, key=secret_key)``.
6. Compare in constant time with the popped hash.

In addition, :func:`verify_init_data` enforces a maximum ``auth_date`` age to
defend against replay of leaked URLs.
"""
from __future__ import annotations

import hmac
import json
from dataclasses import dataclass
from hashlib import sha256
from time import time
from typing import Any
from urllib.parse import parse_qsl


class InitDataInvalidError(Exception):
    """Raised when ``initData`` is malformed or its HMAC does not match."""


class InitDataExpiredError(InitDataInvalidError):
    """Raised when ``auth_date`` is older than the configured maximum age."""


@dataclass(frozen=True)
class TelegramUser:
    """A subset of the Telegram ``WebAppUser`` we care about server-side."""

    id: int
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    language_code: str | None = None
    is_premium: bool = False
    photo_url: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TelegramUser:
        try:
            telegram_id = int(data["id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise InitDataInvalidError("user.id missing or not an integer") from exc
        return cls(
            id=telegram_id,
            first_name=_opt_str(data.get("first_name")),
            last_name=_opt_str(data.get("last_name")),
            username=_opt_str(data.get("username")),
            language_code=_opt_str(data.get("language_code")),
            is_premium=bool(data.get("is_premium", False)),
            photo_url=_opt_str(data.get("photo_url")),
        )


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _build_data_check_string(pairs: list[tuple[str, str]]) -> str:
    pairs_sorted = sorted(pairs, key=lambda kv: kv[0])
    return "\n".join(f"{k}={v}" for k, v in pairs_sorted)


def _expected_hash(data_check_string: str, bot_token: str) -> str:
    secret_key = hmac.new(
        key=b"WebAppData",
        msg=bot_token.encode("utf-8"),
        digestmod=sha256,
    ).digest()
    return hmac.new(
        key=secret_key,
        msg=data_check_string.encode("utf-8"),
        digestmod=sha256,
    ).hexdigest()


def verify_init_data(
    init_data: str,
    bot_token: str,
    *,
    max_age_seconds: int | None = 86400,
    now: float | None = None,
) -> dict[str, Any]:
    """Verify Telegram ``initData`` and return its parsed payload.

    Args:
        init_data: Raw query string from ``Telegram.WebApp.initData``.
        bot_token: Bot token used to derive the HMAC secret.
        max_age_seconds: Reject payloads whose ``auth_date`` is older than this.
            ``None`` disables the age check (use only in tests).
        now: Override the current time (seconds since epoch). Useful in tests.

    Returns:
        A ``dict`` with the parsed payload — nested JSON fields like ``user``
        and ``receiver`` are already decoded into dictionaries.

    Raises:
        InitDataInvalidError: Malformed input, missing ``hash``, or HMAC
            mismatch.
        InitDataExpiredError: ``auth_date`` older than ``max_age_seconds``.
    """
    if not init_data:
        raise InitDataInvalidError("initData is empty")
    if not bot_token:
        raise InitDataInvalidError("bot token is not configured")

    pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=False)
    received_hash: str | None = None
    rest: list[tuple[str, str]] = []
    for key, value in pairs:
        if key == "hash":
            received_hash = value
            continue
        rest.append((key, value))

    if received_hash is None:
        raise InitDataInvalidError("hash field missing")

    expected = _expected_hash(_build_data_check_string(rest), bot_token)
    if not hmac.compare_digest(expected, received_hash):
        raise InitDataInvalidError("hash mismatch")

    payload: dict[str, Any] = {}
    for key, value in rest:
        if key in {"user", "receiver", "chat"} and value:
            try:
                payload[key] = json.loads(value)
            except json.JSONDecodeError as exc:
                raise InitDataInvalidError(
                    f"{key!r} is not valid JSON",
                ) from exc
        else:
            payload[key] = value

    if max_age_seconds is not None:
        try:
            auth_date = int(payload["auth_date"])
        except (KeyError, TypeError, ValueError) as exc:
            raise InitDataInvalidError("auth_date missing or invalid") from exc
        current = now if now is not None else time()
        if current - auth_date > max_age_seconds:
            raise InitDataExpiredError(
                f"initData expired: auth_date={auth_date}, now={int(current)}"
            )

    return payload
