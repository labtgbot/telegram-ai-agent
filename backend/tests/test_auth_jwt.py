"""Unit tests for admin JWT helpers."""
from __future__ import annotations

import pytest

from app.auth.jwt import (
    InvalidTokenError,
    TokenExpiredError,
    create_access_token,
    create_refresh_token,
    decode_token,
)

SECRET = "test-secret-do-not-use-in-prod"


def test_access_token_round_trip() -> None:
    token = create_access_token(
        subject=42, role="super_admin", secret=SECRET, ttl_seconds=120
    )
    claims = decode_token(token, secret=SECRET, expected_type="access")
    assert claims.sub == "42"
    assert claims.role == "super_admin"
    assert claims.type == "access"
    assert claims.exp - claims.iat == 120


def test_refresh_token_round_trip() -> None:
    token = create_refresh_token(
        subject="42", role="support_admin", secret=SECRET, ttl_seconds=600
    )
    claims = decode_token(token, secret=SECRET, expected_type="refresh")
    assert claims.sub == "42"
    assert claims.type == "refresh"


def test_decode_rejects_wrong_secret() -> None:
    token = create_access_token(subject=1, role="user", secret=SECRET)
    with pytest.raises(InvalidTokenError):
        decode_token(token, secret="other-secret")


def test_decode_rejects_wrong_type() -> None:
    token = create_refresh_token(subject=1, role="user", secret=SECRET)
    with pytest.raises(InvalidTokenError):
        decode_token(token, secret=SECRET, expected_type="access")


def test_decode_rejects_garbage() -> None:
    with pytest.raises(InvalidTokenError):
        decode_token("not-a-jwt", secret=SECRET)


def test_decode_raises_when_expired() -> None:
    token = create_access_token(
        subject=1,
        role="analyst",
        secret=SECRET,
        ttl_seconds=-10,  # already in the past
    )
    with pytest.raises(TokenExpiredError):
        decode_token(token, secret=SECRET)


def test_unique_jti_per_token() -> None:
    a = decode_token(
        create_access_token(subject=1, role="x", secret=SECRET),
        secret=SECRET,
    )
    b = decode_token(
        create_access_token(subject=1, role="x", secret=SECRET),
        secret=SECRET,
    )
    assert a.jti != b.jti
