"""PII scrubber for structured log events.

GDPR principle of *data minimisation* requires us to keep log lines free
of personal data we don't strictly need to operate or debug. This module
provides a structlog processor that walks an event dictionary and:

* redacts values whose **key** looks personal (``email``, ``phone``,
  ``password``, ``api_key``, ``token``, ``init_data`` …);
* redacts string **values** that match known PII patterns (email
  addresses, JWTs, Telegram bot tokens) regardless of the key they
  appear under.

A small list of fields is left intact because we rely on them for
correlation (``user_id``, ``request_id``, ``trace_id``, …). The
scrubber is conservative: when in doubt, redact. Callers that need to
log raw PII (e.g. customer-support tooling) should bypass the standard
logger and write to a dedicated, access-controlled audit log instead.

Use :func:`install_log_scrubber` to register the processor at startup,
or :func:`scrub_event` directly for ad-hoc scrubbing inside tests.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Final

import structlog

REDACTED: Final[str] = "[REDACTED]"

# Keys that always carry PII or credentials — value is replaced.
_PII_KEY_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"(?i)pass(word)?$"),
    re.compile(r"(?i)secret$"),
    re.compile(r"(?i)(api[_-]?key|access[_-]?key)$"),
    re.compile(r"(?i)(auth|bearer)[_-]?token$"),
    re.compile(r"(?i)(^|_)token$"),
    re.compile(r"(?i)init[_-]?data$"),
    re.compile(r"(?i)email$"),
    re.compile(r"(?i)phone(_number)?$"),
    re.compile(r"(?i)session[_-]?id$"),
    re.compile(r"(?i)cookie$"),
    re.compile(r"(?i)authorization$"),
    re.compile(r"(?i)credit[_-]?card$"),
    re.compile(r"(?i)card[_-]?number$"),
    re.compile(r"(?i)cvv$"),
)

# String patterns scrubbed regardless of the key they appear under.
_EMAIL_RE: Final[re.Pattern[str]] = re.compile(
    r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b"
)
# JWTs (three base64url segments separated by dots, ≥10 chars each).
_JWT_RE: Final[re.Pattern[str]] = re.compile(
    r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"
)
# Telegram bot tokens are ``<bot-id>:<35-char-base64-ish-string>``.
_TG_BOT_TOKEN_RE: Final[re.Pattern[str]] = re.compile(
    r"\b\d{6,}:[A-Za-z0-9_-]{30,}\b"
)
# 16-digit credit-card numbers (with optional spaces or dashes).
_CC_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:\d[ -]?){13,19}\b"
)

# Keys that we keep verbatim — these are diagnostic identifiers, not PII.
_SAFE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "event",
        "level",
        "logger",
        "timestamp",
        "request_id",
        "trace_id",
        "span_id",
        "user_id",
        "telegram_id",
        "chat_id",
        "thread_id",
        "job_id",
        "status",
        "duration_ms",
        "error",
        "error_code",
        "method",
        "path",
        "route",
        "endpoint",
    }
)


def _key_is_pii(key: str) -> bool:
    if key in _SAFE_KEYS:
        return False
    return any(pat.search(key) for pat in _PII_KEY_PATTERNS)


def _scrub_value_string(value: str) -> str:
    out = _EMAIL_RE.sub(REDACTED, value)
    out = _JWT_RE.sub(REDACTED, out)
    out = _TG_BOT_TOKEN_RE.sub(REDACTED, out)
    out = _CC_RE.sub(REDACTED, out)
    return out


def _scrub_value(key: str, value: Any) -> Any:
    """Scrub ``value`` based on its ``key`` and shape.

    * If the key looks like PII → replace entirely with ``[REDACTED]``.
    * If the value is a string → run regex-based PII scrubbing.
    * If the value is a mapping or list → recurse so nested fields are
      cleaned too.
    """
    if _key_is_pii(key):
        return REDACTED
    if isinstance(value, str):
        return _scrub_value_string(value)
    if isinstance(value, Mapping):
        return {k: _scrub_value(str(k), v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        cleaned = [_scrub_value(key, item) for item in value]
        return type(value)(cleaned) if isinstance(value, tuple) else cleaned
    return value


def scrub_event(event_dict: dict[str, Any]) -> dict[str, Any]:
    """Scrub a structlog event dict in place and return it."""
    for key in list(event_dict.keys()):
        event_dict[key] = _scrub_value(key, event_dict[key])
    return event_dict


def scrub_processor(
    _logger: Any, _method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Structlog processor entry point — see :func:`scrub_event`."""
    return scrub_event(event_dict)


def install_log_scrubber() -> None:
    """Prepend the scrubber to structlog's processor chain.

    Safe to call after :func:`app.core.logging.configure_logging` —
    the scrubber runs before the final renderer so JSON / console
    output never sees raw PII.
    """
    current = structlog.get_config()
    processors = list(current.get("processors") or [])
    if scrub_processor in processors:
        return
    # Insert just before the final renderer (last entry).
    if processors:
        processors.insert(len(processors) - 1, scrub_processor)
    else:
        processors = [scrub_processor]
    structlog.configure(processors=processors)
