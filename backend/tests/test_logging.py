"""Tests for structured JSON logging.

We exercise both rendering modes (``json`` and ``console``) and confirm the
JSON output produces a parseable record with the standard fields Loki and
ELK pipelines rely on.
"""
from __future__ import annotations

import io
import json
import logging
from contextlib import redirect_stdout

import pytest
import structlog

from app.core import logging as app_logging
from app.core.config import Settings


def _reset_logging_state() -> None:
    """Allow ``configure_logging`` to run again with fresh settings."""
    app_logging._configured = False
    structlog.reset_defaults()
    # also reset stdlib root handlers so successive tests don't accumulate
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)


@pytest.fixture(autouse=True)
def _isolated_logging() -> None:
    _reset_logging_state()
    yield
    _reset_logging_state()


def _capture(fn) -> str:
    buf = io.StringIO()
    with redirect_stdout(buf):
        fn()
    return buf.getvalue()


def test_json_log_format_emits_parseable_records() -> None:
    settings = Settings(log_level="INFO", log_format="json")
    app_logging.configure_logging(settings)
    logger = app_logging.get_logger("test")

    output = _capture(lambda: logger.info("event_under_test", user_id=123, action="purchase"))

    line = output.strip().splitlines()[-1]
    record = json.loads(line)
    assert record["event"] == "event_under_test"
    assert record["user_id"] == 123
    assert record["action"] == "purchase"
    assert record["level"] == "info"
    assert "timestamp" in record


def test_json_log_includes_iso_utc_timestamp() -> None:
    settings = Settings(log_level="INFO", log_format="json")
    app_logging.configure_logging(settings)
    logger = app_logging.get_logger("test")

    output = _capture(lambda: logger.info("tick"))
    line = output.strip().splitlines()[-1]
    record = json.loads(line)
    # ISO-8601 with UTC indicator
    assert record["timestamp"].endswith("Z") or "+00:00" in record["timestamp"]


def test_console_log_format_is_human_readable_not_json() -> None:
    settings = Settings(log_level="INFO", log_format="console")
    app_logging.configure_logging(settings)
    logger = app_logging.get_logger("test")

    output = _capture(lambda: logger.info("event_human", user_id=1))
    line = output.strip().splitlines()[-1]
    with pytest.raises(json.JSONDecodeError):
        json.loads(line)
    assert "event_human" in line


def test_configure_logging_is_idempotent() -> None:
    settings = Settings(log_level="INFO", log_format="json")
    app_logging.configure_logging(settings)
    first_state = app_logging._configured
    app_logging.configure_logging(settings)
    assert first_state is True
    assert app_logging._configured is True


def test_log_level_respected() -> None:
    settings = Settings(log_level="WARNING", log_format="json")
    app_logging.configure_logging(settings)
    logger = app_logging.get_logger("test")

    output = _capture(lambda: logger.info("should_be_dropped"))
    assert "should_be_dropped" not in output

    output = _capture(lambda: logger.warning("should_pass"))
    assert "should_pass" in output
