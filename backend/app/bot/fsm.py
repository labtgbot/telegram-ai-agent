"""Redis-backed FSM (finite-state machine) for multi-step bot flows.

Phase 1 doesn't use long state chains, but ``/buy`` will (pick package →
confirm → invoice).  Keeping the storage primitive here means handlers can
adopt it incrementally without rewriting glue.
"""
from __future__ import annotations

import json
from typing import Any


class RedisFSM:
    """Minimal per-user state store keyed by ``telegram_id``.

    State is stored as JSON under ``bot:fsm:<telegram_id>`` with the
    configured TTL (default 24 hours).  The ``set`` method overwrites; use
    :py:meth:`update` for partial merges.
    """

    def __init__(self, redis: Any, *, ttl_seconds: int = 24 * 60 * 60) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    @staticmethod
    def _key(telegram_id: int) -> str:
        return f"bot:fsm:{telegram_id}"

    async def get(self, telegram_id: int) -> dict[str, Any]:
        raw = await self._redis.get(self._key(telegram_id))
        if raw is None:
            return {}
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    async def set(self, telegram_id: int, state: dict[str, Any]) -> None:
        await self._redis.set(
            self._key(telegram_id),
            json.dumps(state, separators=(",", ":")),
            ex=self._ttl,
        )

    async def update(self, telegram_id: int, **changes: Any) -> dict[str, Any]:
        current = await self.get(telegram_id)
        current.update(changes)
        await self.set(telegram_id, current)
        return current

    async def clear(self, telegram_id: int) -> None:
        await self._redis.delete(self._key(telegram_id))
