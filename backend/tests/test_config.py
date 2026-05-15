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
