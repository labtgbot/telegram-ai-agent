"""Tests for ``app.core.sentry``.

Sentry must remain DSN-gated so local development and CI never ship events.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.core import sentry as sentry_module
from app.core.config import Settings


@pytest.fixture(autouse=True)
def _reset_sentry() -> None:
    sentry_module.reset_for_tests()
    yield
    sentry_module.reset_for_tests()


def test_init_sentry_no_op_when_dsn_empty() -> None:
    settings = Settings(sentry_dsn="")
    with patch("sentry_sdk.init") as fake_init:
        assert sentry_module.init_sentry(settings) is False
        fake_init.assert_not_called()


def test_init_sentry_whitespace_dsn_treated_as_empty() -> None:
    settings = Settings(sentry_dsn="   ")
    with patch("sentry_sdk.init") as fake_init:
        assert sentry_module.init_sentry(settings) is False
        fake_init.assert_not_called()


def test_init_sentry_initialises_when_dsn_present() -> None:
    settings = Settings(
        sentry_dsn="https://public@o0.ingest.sentry.io/0",
        sentry_environment="staging",
        sentry_release="my-app@1.2.3",
        sentry_traces_sample_rate=0.5,
        sentry_profiles_sample_rate=0.25,
    )
    with patch("sentry_sdk.init") as fake_init, patch("sentry_sdk.set_tag") as fake_tag:
        assert sentry_module.init_sentry(settings) is True
        fake_init.assert_called_once()
        kwargs = fake_init.call_args.kwargs
        assert kwargs["dsn"] == "https://public@o0.ingest.sentry.io/0"
        assert kwargs["environment"] == "staging"
        assert kwargs["release"] == "my-app@1.2.3"
        assert kwargs["traces_sample_rate"] == 0.5
        assert kwargs["profiles_sample_rate"] == 0.25
        assert kwargs["send_default_pii"] is False
        fake_tag.assert_called_once_with("service", "backend")


def test_init_sentry_uses_app_env_when_environment_unset() -> None:
    settings = Settings(
        sentry_dsn="https://public@o0.ingest.sentry.io/0",
        sentry_environment="",
        app_env="production",
    )
    with patch("sentry_sdk.init") as fake_init:
        sentry_module.init_sentry(settings)
        assert fake_init.call_args.kwargs["environment"] == "production"


def test_init_sentry_only_runs_once() -> None:
    settings = Settings(sentry_dsn="https://public@o0.ingest.sentry.io/0")
    with patch("sentry_sdk.init") as fake_init:
        assert sentry_module.init_sentry(settings) is True
        assert sentry_module.init_sentry(settings) is False
        fake_init.assert_called_once()


def test_reset_for_tests_allows_re_initialisation() -> None:
    settings = Settings(sentry_dsn="https://public@o0.ingest.sentry.io/0")
    with patch("sentry_sdk.init") as fake_init:
        sentry_module.init_sentry(settings)
        sentry_module.reset_for_tests()
        assert sentry_module.init_sentry(settings) is True
        assert fake_init.call_count == 2
