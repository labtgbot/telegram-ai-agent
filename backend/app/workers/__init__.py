"""Background worker entrypoints.

Phase 2 ships with the subscription-renewal task only.  Phase 3 will wire
these into Celery beat (see ``docs/ARCHITECTURE.md > Workers``); for now
the functions are directly invokable via ``python -m app.workers.subscriptions``
or from an external scheduler such as cron.
"""
from app.workers.subscriptions import run_subscription_renewals

__all__ = ["run_subscription_renewals"]
