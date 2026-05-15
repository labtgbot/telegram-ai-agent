"""Structured logging via structlog.

Configures stdlib ``logging`` and ``structlog`` to emit either JSON (prod) or
human-readable console output (dev), selected by ``LOG_FORMAT``.

Call :func:`configure_logging` once during application startup. Subsequent
calls are idempotent — repeated startup hooks won't double-install processors.
"""
from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from app.core.config import Settings, get_settings

_configured: bool = False


def _shared_processors() -> list[Any]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]


def configure_logging(settings: Settings | None = None) -> None:
    """Install structlog + stdlib bridge.

    Safe to call multiple times: a module-level flag prevents reconfiguration.
    """
    global _configured
    if _configured:
        return

    cfg = settings or get_settings()
    level = getattr(logging, cfg.log_level.upper(), logging.INFO)

    if cfg.log_format == "console":
        renderer: Any = structlog.dev.ConsoleRenderer(colors=False)
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[*_shared_processors(), renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Bridge stdlib loggers (uvicorn, sqlalchemy, alembic) into structlog.
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    for noisy in ("uvicorn.access",):
        logging.getLogger(noisy).setLevel(max(level, logging.INFO))

    _configured = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a configured structlog logger.

    Auto-configures with default settings if :func:`configure_logging` was not
    called explicitly — useful in scripts and tests.
    """
    if not _configured:
        configure_logging()
    return structlog.get_logger(name)
