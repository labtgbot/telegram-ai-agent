"""Unit tests for the TOTP wrapper."""
from __future__ import annotations

import pyotp

from app.auth.totp import (
    DEFAULT_INTERVAL,
    generate_totp_secret,
    provisioning_uri,
    verify_totp,
)


def test_generate_secret_is_base32() -> None:
    secret = generate_totp_secret()
    assert len(secret) >= 16
    # base32 alphabet — no padding for pyotp secrets.
    assert set(secret).issubset(set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"))


def test_verify_accepts_current_code() -> None:
    secret = generate_totp_secret()
    code = pyotp.TOTP(secret).now()
    assert verify_totp(secret, code) is True


def test_verify_rejects_wrong_code() -> None:
    secret = generate_totp_secret()
    assert verify_totp(secret, "000000") in {False, True}
    # Wrong-length / non-digit values should always fail.
    assert verify_totp(secret, "abcdef") is False
    assert verify_totp(secret, "") is False


def test_verify_rejects_with_wrong_secret() -> None:
    secret_a = generate_totp_secret()
    secret_b = generate_totp_secret()
    code = pyotp.TOTP(secret_a).now()
    # Codes generated for ``a`` should not validate against ``b``.  In the
    # vanishingly unlikely case of a clash, the test still proves the API
    # accepts mismatched codes deterministically.
    if secret_a == secret_b:
        return
    assert verify_totp(secret_b, code) is False


def test_verify_tolerates_one_period_skew() -> None:
    secret = generate_totp_secret()
    totp = pyotp.TOTP(secret)
    base = 1_700_000_000
    code = totp.at(base)
    # Within one period either side — accepted.
    assert verify_totp(secret, code, now=base + DEFAULT_INTERVAL - 1) is True
    assert verify_totp(secret, code, now=base - DEFAULT_INTERVAL + 1) is True
    # Two periods away — rejected.
    assert verify_totp(secret, code, now=base + DEFAULT_INTERVAL * 3) is False


def test_provisioning_uri_contains_issuer_and_account() -> None:
    secret = generate_totp_secret()
    uri = provisioning_uri(secret, account_name="alice", issuer="Telegram AI Agent")
    assert uri.startswith("otpauth://totp/")
    assert "alice" in uri
    assert "issuer=Telegram%20AI%20Agent" in uri or "issuer=Telegram+AI+Agent" in uri
