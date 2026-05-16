"""Background worker entrypoints.

Phase 2 ships with two tasks:

* :func:`run_subscription_renewals` — daily auto-renew sweep
  (``python -m app.workers.subscriptions``);
* :func:`run_video_polling_pass` — short-interval video-job poll
  (``python -m app.workers.video_polling``).

Phase 3 will wire these into Celery beat (see
``docs/ARCHITECTURE.md > Workers``); for now the functions are directly
invokable via the corresponding module entrypoints or from an external
scheduler such as cron.

The submodules are exposed lazily via PEP 562 ``__getattr__`` to avoid
pulling the full ``app.bot`` / ``app.services.payments`` graph at package
import time — the workers are launched as ``python -m
app.workers.<task>``, which triggers this ``__init__`` first, so an
eager re-export would deadlock on the pre-existing
``payments ↔ bot.handlers`` import cycle.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.workers.subscriptions import run_subscription_renewals
    from app.workers.video_polling import (
        run_video_polling_loop,
        run_video_polling_pass,
    )

__all__ = [
    "run_subscription_renewals",
    "run_video_polling_loop",
    "run_video_polling_pass",
]

_LAZY: dict[str, tuple[str, str]] = {
    "run_subscription_renewals": ("app.workers.subscriptions", "run_subscription_renewals"),
    "run_video_polling_pass": ("app.workers.video_polling", "run_video_polling_pass"),
    "run_video_polling_loop": ("app.workers.video_polling", "run_video_polling_loop"),
}


def __getattr__(name: str) -> Any:
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module 'app.workers' has no attribute {name!r}")
    module_name, attr = target
    from importlib import import_module

    module = import_module(module_name)
    return getattr(module, attr)
