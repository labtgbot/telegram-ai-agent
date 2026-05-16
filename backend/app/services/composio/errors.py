"""Error hierarchy for the Composio MCP client.

Callers that wrap :class:`ComposioClient` typically branch on these
exceptions:

* :class:`ComposioInvalidToolError` — programming error (unknown
  service_type / tool); never retried.
* :class:`ComposioAuthError` — credentials problem; never retried.
* :class:`ComposioTransientError` — network / 5xx / 429; the client
  retries up to ``COMPOSIO_MAX_RETRIES`` times before re-raising.
* :class:`ComposioError` — everything else, including 4xx responses.
"""

from __future__ import annotations


class ComposioError(Exception):
    """Base class for every Composio-related failure."""


class ComposioInvalidToolError(ComposioError):
    """Raised when the requested tool / service_type is not configured."""


class ComposioAuthError(ComposioError):
    """Raised for 401 / 403 responses — credentials must be fixed."""


class ComposioTransientError(ComposioError):
    """Raised for 408 / 429 / 5xx responses or network errors.

    The client retries these with exponential backoff.  When the retry
    budget is exhausted the last exception bubbles up to the caller.
    """

    def __init__(self, message: str, *, attempts: int = 1) -> None:
        super().__init__(message)
        self.attempts = attempts


__all__ = [
    "ComposioAuthError",
    "ComposioError",
    "ComposioInvalidToolError",
    "ComposioTransientError",
]
