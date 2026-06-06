"""Settings and logging configuration tests."""

from __future__ import annotations

import importlib
import logging

import pytest


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    from app.core import config as config_module

    importlib.reload(config_module)
    config_module.get_settings.cache_clear()

    s = config_module.get_settings()
    assert s.app_env == "development"
    assert s.api_v1_prefix == "/api/v1"
    assert s.redis_url.startswith("redis://")
    assert s.database_url.startswith("postgresql+asyncpg://")
    assert s.is_development is True


def test_settings_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.setenv("REDIS_URL", "redis://example:6380/2")

    from app.core import config as config_module

    importlib.reload(config_module)
    config_module.get_settings.cache_clear()

    s = config_module.get_settings()
    assert s.app_env == "production"
    assert s.log_level == "WARNING"
    assert s.redis_url == "redis://example:6380/2"
    assert s.is_development is False


def test_sync_database_url_translation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://u:p@h:5432/db",
    )
    from app.core import config as config_module

    importlib.reload(config_module)
    config_module.get_settings.cache_clear()

    s = config_module.get_settings()
    assert s.sync_database_url == "postgresql+psycopg://u:p@h:5432/db"


def test_configure_logging_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("LOG_FORMAT", "console")
    from app.core import config as config_module
    from app.core import logging as logging_module

    importlib.reload(config_module)
    config_module.get_settings.cache_clear()
    importlib.reload(logging_module)

    logging_module.configure_logging()
    handlers_before = list(logging.getLogger().handlers)
    logging_module.configure_logging()
    handlers_after = list(logging.getLogger().handlers)
    assert handlers_before == handlers_after

    logger = logging_module.get_logger("test")
    logger.info("hello", key="value")


def _fresh_config_module():
    """Re-import config module so tests see consistent class identity.

    Earlier tests in this file call ``importlib.reload(config_module)``,
    which replaces ``Settings`` / ``InsecureDefaultSecretError`` with
    new class objects. Importing inside each test keeps assertions
    aligned with whatever class identity is current at call time.
    """
    from app.core import config as config_module

    return config_module


def test_assert_production_safe_blocks_default_jwt_secret() -> None:
    config_module = _fresh_config_module()
    settings = config_module.Settings(
        app_env="production",
        admin_jwt_secret="change-me",
    )
    with pytest.raises(config_module.InsecureDefaultSecretError) as excinfo:
        settings.assert_production_safe()
    assert "ADMIN_JWT_SECRET" in str(excinfo.value)


def test_assert_production_safe_blocks_empty_jwt_secret() -> None:
    config_module = _fresh_config_module()
    settings = config_module.Settings(
        app_env="staging",
        admin_jwt_secret="",
        telegram_webhook_secret="webhook-secret",
    )
    with pytest.raises(config_module.InsecureDefaultSecretError):
        settings.assert_production_safe()


def test_assert_production_safe_blocks_empty_telegram_webhook_secret() -> None:
    config_module = _fresh_config_module()
    settings = config_module.Settings(
        app_env="production",
        admin_jwt_secret="a-real-long-random-secret-9f8e",
        telegram_webhook_secret="",
    )
    with pytest.raises(config_module.InsecureDefaultSecretError) as excinfo:
        settings.assert_production_safe()
    assert "TELEGRAM_WEBHOOK_SECRET" in str(excinfo.value)


def test_assert_production_safe_allows_dev_with_default_secret() -> None:
    config_module = _fresh_config_module()
    for env in ("development", "local", "test", "ci"):
        config_module.Settings(app_env=env, admin_jwt_secret="change-me").assert_production_safe()


def test_assert_production_safe_allows_custom_secret_in_production() -> None:
    config_module = _fresh_config_module()
    config_module.Settings(
        app_env="production",
        admin_jwt_secret="a-real-long-random-secret-9f8e",
        telegram_webhook_secret="telegram-webhook-secret",
    ).assert_production_safe()
