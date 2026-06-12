"""Background worker entrypoints.

Production runs these modules directly from the backend image:

* ``python -m app.workers.broadcast --loop`` for broadcast delivery;
* ``python -m app.workers.video_polling --loop`` for video job polling;
* Kubernetes CronJobs or compose loops for subscriptions, account deletion,
  daily analytics, and token usage partition maintenance.

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
    from app.workers.account_deletion import process_due_deletions
    from app.workers.broadcast import run_broadcast_loop, run_broadcast_pass
    from app.workers.daily_analytics import run_daily_analytics
    from app.workers.subscriptions import run_subscription_renewals
    from app.workers.token_usage_partitions import (
        run_token_usage_partition_maintenance,
    )
    from app.workers.video_polling import (
        run_video_polling_loop,
        run_video_polling_pass,
    )

__all__ = [
    "process_due_deletions",
    "run_broadcast_loop",
    "run_broadcast_pass",
    "run_daily_analytics",
    "run_subscription_renewals",
    "run_token_usage_partition_maintenance",
    "run_video_polling_loop",
    "run_video_polling_pass",
]

_LAZY: dict[str, tuple[str, str]] = {
    "process_due_deletions": ("app.workers.account_deletion", "process_due_deletions"),
    "run_broadcast_loop": ("app.workers.broadcast", "run_broadcast_loop"),
    "run_broadcast_pass": ("app.workers.broadcast", "run_broadcast_pass"),
    "run_daily_analytics": ("app.workers.daily_analytics", "run_daily_analytics"),
    "run_subscription_renewals": (
        "app.workers.subscriptions",
        "run_subscription_renewals",
    ),
    "run_token_usage_partition_maintenance": (
        "app.workers.token_usage_partitions",
        "run_token_usage_partition_maintenance",
    ),
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
