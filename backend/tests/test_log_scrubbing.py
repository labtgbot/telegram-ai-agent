"""Unit tests for ``app.core.log_scrubbing``.

The scrubber's contract is "no PII leaves the log pipeline" — these tests
pin the redaction rules so a future regression is caught immediately.
"""
from __future__ import annotations

from app.core.log_scrubbing import REDACTED, scrub_event


def test_pii_keys_are_redacted() -> None:
    event = {
        "event": "auth.attempt",
        "password": "hunter2",
        "api_key": "sk-xxxx",
        "init_data": "user=%7B%22id%22%3A1%7D&hash=abc",
        "email": "alice@example.com",
        "phone": "+1 555 0100",
        "authorization": "Bearer xxx",
        "user_id": 42,
    }
    out = scrub_event(dict(event))
    assert out["password"] == REDACTED
    assert out["api_key"] == REDACTED
    assert out["init_data"] == REDACTED
    assert out["email"] == REDACTED
    assert out["phone"] == REDACTED
    assert out["authorization"] == REDACTED
    # Safe fields stay intact.
    assert out["event"] == "auth.attempt"
    assert out["user_id"] == 42


def test_emails_inside_strings_are_redacted() -> None:
    event = {"event": "support.note", "message": "contact alice@example.com asap"}
    out = scrub_event(dict(event))
    assert "alice@example.com" not in out["message"]
    assert REDACTED in out["message"]


def test_jwt_in_value_is_redacted() -> None:
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NSJ9.dBjftJeZ4CVPmB92K27uhbUJU1p1r-aaaaaa"
    event = {"event": "auth.ok", "message": f"raw token: {jwt}"}
    out = scrub_event(dict(event))
    assert jwt not in out["message"]
    assert REDACTED in out["message"]


def test_telegram_bot_token_is_redacted() -> None:
    bot_token = "1234567890:AAEhBP0av28-abcdefghijklmnopqrstuvwxyz"
    event = {"event": "bot.boot", "details": f"using {bot_token}"}
    out = scrub_event(dict(event))
    assert bot_token not in out["details"]
    assert REDACTED in out["details"]


def test_credit_card_in_value_is_redacted() -> None:
    event = {"event": "payment", "memo": "card 4111 1111 1111 1111 declined"}
    out = scrub_event(dict(event))
    assert "4111 1111 1111 1111" not in out["memo"]
    assert REDACTED in out["memo"]


def test_nested_structures_are_scrubbed() -> None:
    event = {
        "event": "webhook",
        "payload": {
            "user": {"email": "bob@example.com", "id": 7},
            "tokens": ["safe", "bob@example.com"],
        },
    }
    out = scrub_event(dict(event))
    inner = out["payload"]["user"]
    assert inner["email"] == REDACTED
    assert inner["id"] == 7
    assert out["payload"]["tokens"][1] == REDACTED


def test_safe_keys_are_not_scrubbed() -> None:
    event = {
        "event": "request.done",
        "request_id": "req-123",
        "trace_id": "trace-xyz",
        "user_id": 42,
        "duration_ms": 12,
    }
    out = scrub_event(dict(event))
    assert out == event
