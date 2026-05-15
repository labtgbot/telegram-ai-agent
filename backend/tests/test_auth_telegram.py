"""Unit tests for Telegram WebApp ``initData`` HMAC verification."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest

from app.auth.telegram import (
    InitDataExpiredError,
    InitDataInvalidError,
    TelegramUser,
    verify_init_data,
)

BOT_TOKEN = "1234567890:TEST-AAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


def _build_init_data(
    *,
    user: dict | None = None,
    auth_date: int | None = None,
    query_id: str = "AAEvAAAAAA",
    extra: dict[str, str] | None = None,
    bot_token: str = BOT_TOKEN,
    tamper_hash: bool = False,
) -> str:
    """Construct a signed initData query string for the tests."""
    user = user or {
        "id": 42,
        "first_name": "Alice",
        "username": "alice",
        "language_code": "en",
    }
    pairs: list[tuple[str, str]] = [
        ("query_id", query_id),
        ("user", json.dumps(user, separators=(",", ":"))),
        ("auth_date", str(auth_date if auth_date is not None else int(time.time()))),
    ]
    if extra:
        pairs.extend(extra.items())
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(pairs, key=lambda p: p[0]))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    if tamper_hash:
        digest = "0" * len(digest)
    pairs.append(("hash", digest))
    return urlencode(pairs)


def test_valid_init_data_returns_parsed_user() -> None:
    init_data = _build_init_data()
    payload = verify_init_data(init_data, BOT_TOKEN, max_age_seconds=60)
    assert payload["query_id"] == "AAEvAAAAAA"
    assert payload["user"]["id"] == 42
    assert payload["user"]["username"] == "alice"


def test_tampered_hash_raises() -> None:
    init_data = _build_init_data(tamper_hash=True)
    with pytest.raises(InitDataInvalidError):
        verify_init_data(init_data, BOT_TOKEN, max_age_seconds=60)


def test_tampered_payload_raises() -> None:
    init_data = _build_init_data()
    # Flip ``user`` content but keep original hash.
    tampered = init_data.replace("Alice", "Mallory")
    with pytest.raises(InitDataInvalidError):
        verify_init_data(tampered, BOT_TOKEN, max_age_seconds=60)


def test_expired_init_data_raises() -> None:
    init_data = _build_init_data(auth_date=100)
    with pytest.raises(InitDataExpiredError):
        verify_init_data(init_data, BOT_TOKEN, max_age_seconds=60, now=10_000.0)


def test_wrong_bot_token_raises() -> None:
    init_data = _build_init_data(bot_token="another-token")
    with pytest.raises(InitDataInvalidError):
        verify_init_data(init_data, BOT_TOKEN, max_age_seconds=60)


def test_missing_hash_raises() -> None:
    init_data = "query_id=x&auth_date=1"
    with pytest.raises(InitDataInvalidError):
        verify_init_data(init_data, BOT_TOKEN, max_age_seconds=60)


def test_empty_init_data_raises() -> None:
    with pytest.raises(InitDataInvalidError):
        verify_init_data("", BOT_TOKEN)


def test_empty_bot_token_raises() -> None:
    with pytest.raises(InitDataInvalidError):
        verify_init_data("foo=bar&hash=x", "")


def test_max_age_disabled_passes_old_data() -> None:
    init_data = _build_init_data(auth_date=100)
    payload = verify_init_data(init_data, BOT_TOKEN, max_age_seconds=None)
    assert payload["auth_date"] == "100"


def test_telegram_user_from_dict_normalizes_fields() -> None:
    tg = TelegramUser.from_dict(
        {"id": "7", "first_name": "Bob", "username": "", "is_premium": True}
    )
    assert tg.id == 7
    assert tg.username is None  # empty string normalized to None
    assert tg.is_premium is True


def test_telegram_user_from_dict_rejects_missing_id() -> None:
    with pytest.raises(InitDataInvalidError):
        TelegramUser.from_dict({"first_name": "x"})
