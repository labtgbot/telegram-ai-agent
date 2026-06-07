"""Text-generation domain service.

Phase-2 sibling of :mod:`app.services.image_generation` and
:mod:`app.services.video_generation`.  The same Composio toolkit
gateway, ``TokenService`` debit pattern and ``token_usage_logs`` audit
shape are reused — only the request/response payloads and the conversation
history layer are new.

Three modes are supported (see issue #15):

* ``basic`` (1 token)               — quick Q&A via Gemini.
* ``advanced`` (5 tokens)           — longer, higher-quality answers via Claude.
* ``autonomous_agent`` (10 tokens)  — agent-style answers (tool use, multi-step
  reasoning) via GPT.

Operators can rebind any mode to a different toolkit through
``admin_settings.ai_routing`` — the override map is forwarded to
:func:`app.services.composio.resolve_tool`.

Conversation history is opaque to this service: the caller supplies a
:class:`ConversationHistory` (Redis-backed for free users, DB-backed for
premium) and the service simply asks it to load/append turns around each
Composio invocation.  An optional :class:`SummaryStrategy` collapses old
turns when the thread grows past a configurable threshold so subsequent
prompts stay within token budgets.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final, Protocol

from redis.asyncio import Redis
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.chat_history import ChatMessage, ChatThread
from app.services.balance_cache import get_default_balance_cache
from app.services.composio import (
    ComposioClient,
    ComposioError,
    ToolResult,
    log_invocation,
)
from app.services.token_service import TokenService

logger = get_logger(__name__)


# ----------------------------------------------------------------- constants

SERVICE_TYPE: Final[str] = "text"

MODE_BASIC: Final[str] = "basic"
MODE_ADVANCED: Final[str] = "advanced"
MODE_AGENT: Final[str] = "autonomous_agent"

MODE_COST: Final[dict[str, int]] = {
    MODE_BASIC: 1,
    MODE_ADVANCED: 5,
    MODE_AGENT: 10,
}

# Per-mode Composio toolkit override.  ``basic`` falls through to the default
# mapping in :data:`SERVICE_TYPE_TO_TOOL` (gemini); the other modes A/B at the
# call site so admins don't need a redeploy to flip providers.
MODE_TOOLKIT: Final[dict[str, str]] = {
    MODE_BASIC: "gemini",
    MODE_ADVANCED: "claude",
    MODE_AGENT: "openai_gpt",
}

SUPPORTED_MODES: Final[frozenset[str]] = frozenset(MODE_COST.keys())

ROLE_SYSTEM: Final[str] = "system"
ROLE_USER: Final[str] = "user"
ROLE_ASSISTANT: Final[str] = "assistant"
ROLE_SUMMARY: Final[str] = "summary"
KNOWN_ROLES: Final[frozenset[str]] = frozenset(
    {ROLE_SYSTEM, ROLE_USER, ROLE_ASSISTANT, ROLE_SUMMARY}
)

# Validation envelope — keep parity with the image service so the API layer
# can render the same 400/422 surface.
MAX_PROMPT_LENGTH: Final[int] = 4000
MAX_SYSTEM_PROMPT_LENGTH: Final[int] = 2000
MAX_MESSAGE_LENGTH: Final[int] = 8000
DEFAULT_TEMPERATURE: Final[float] = 0.7
MIN_TEMPERATURE: Final[float] = 0.0
MAX_TEMPERATURE: Final[float] = 2.0
DEFAULT_MAX_TOKENS: Final[int] = 1024
MIN_MAX_TOKENS: Final[int] = 1
MAX_MAX_TOKENS: Final[int] = 4096

# History sliding-window defaults.  Override via the ``Settings`` knobs
# (``text_history_*``) if needed; the service prefers caller-passed values
# so different surfaces (bot vs. mini-app) can tune independently.
DEFAULT_HISTORY_TTL_SECONDS: Final[int] = 24 * 3600
DEFAULT_HISTORY_MAX_TURNS: Final[int] = 20
DEFAULT_SUMMARY_TRIGGER_TURNS: Final[int] = 16
DEFAULT_SUMMARY_KEEP_TURNS: Final[int] = 4

# Pseudo-streaming chunk size (characters).  Composio doesn't expose a real
# streaming endpoint yet, so SSE consumers receive sliced chunks of the final
# response — enough for the Mini-App to render a typewriter effect today
# without locking us out of true streaming later.
DEFAULT_STREAM_CHUNK_SIZE: Final[int] = 64

# Redis key prefix for per-thread history.  Keep the prefix in one place so
# ops can scan ``chat:hist:*`` for capacity planning.
REDIS_THREAD_KEY_PREFIX: Final[str] = "chat:hist"


# ----------------------------------------------------------------- errors


class TextGenerationError(Exception):
    """Base class for text-generation errors."""


class InvalidModeError(TextGenerationError):
    """Raised when ``mode`` is outside :data:`SUPPORTED_MODES`."""


class InvalidPromptError(TextGenerationError):
    """Raised when prompt / system_prompt is empty or too long."""


class InvalidTemperatureError(TextGenerationError):
    """Raised when ``temperature`` is outside ``[0.0, 2.0]``."""


class InvalidMaxTokensError(TextGenerationError):
    """Raised when ``max_tokens`` is outside ``[1, 4096]``."""


class TextProviderError(TextGenerationError):
    """Raised when the Composio text toolkit returns a non-recoverable error.

    Exposes ``provider_error`` so the API / bot layer can include the
    upstream message in its response without re-reading the raw payload.
    """

    def __init__(self, message: str, *, provider_error: str | None = None) -> None:
        super().__init__(message)
        self.provider_error = provider_error


# --------------------------------------------------------------- data types


@dataclass(frozen=True)
class ChatTurn:
    """A single message in a conversation thread.

    The shape is intentionally provider-agnostic: ``role`` follows the
    OpenAI/Anthropic vocabulary, ``content`` is plain text.  Optional
    ``meta`` carries provider-specific fields (tool calls, citations)
    when the caller wants to round-trip them through history.
    """

    role: str
    content: str
    meta: dict[str, Any] | None = None
    created_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.meta:
            out["meta"] = self.meta
        if self.created_at is not None:
            out["created_at"] = self.created_at.isoformat()
        return out

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ChatTurn:
        role = str(raw.get("role") or ROLE_USER).strip().lower()
        if role not in KNOWN_ROLES:
            role = ROLE_USER
        created_raw = raw.get("created_at")
        created_at: datetime | None = None
        if isinstance(created_raw, str) and created_raw:
            try:
                created_at = datetime.fromisoformat(created_raw)
            except ValueError:
                created_at = None
        return cls(
            role=role,
            content=str(raw.get("content") or ""),
            meta=raw.get("meta") if isinstance(raw.get("meta"), dict) else None,
            created_at=created_at,
        )


@dataclass(frozen=True)
class TextGenerationResult:
    """Outcome of a successful generation call."""

    user_id: int
    prompt: str
    mode: str
    text: str
    tokens_spent: int
    new_balance: int
    composio_tool: str
    mcp_server: str | None
    processing_time_ms: int | None
    usage_log_id: int
    transaction_id: int
    request_id: str | None = None
    thread_id: str | None = None
    history: tuple[ChatTurn, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class TextChunk:
    """One unit emitted by :meth:`TextGenerationService.iter_generate`.

    ``kind`` is one of ``"delta"`` (incremental text) or ``"final"``
    (terminal marker carrying the full :class:`TextGenerationResult`).
    Streaming consumers should accumulate ``content`` from deltas and
    use the final marker for accounting / "done" UI state.
    """

    kind: str
    content: str = ""
    result: TextGenerationResult | None = None


# ------------------------------------------------------------ history layer


class ConversationHistory(Protocol):
    """Storage protocol for chat threads.

    Implementations live alongside this module (Redis for free users,
    DB-backed for premium).  Methods are async so both back-ends can
    share the same interface.
    """

    async def load(self, user_id: int, thread_id: str) -> list[ChatTurn]: ...

    async def replace(self, user_id: int, thread_id: str, turns: Sequence[ChatTurn]) -> None: ...

    async def append(self, user_id: int, thread_id: str, turns: Sequence[ChatTurn]) -> None: ...

    async def delete(self, user_id: int, thread_id: str) -> None: ...


class RedisConversationHistory:
    """Free-tier history: a JSON list parked in Redis with a sliding TTL.

    Each thread is stored under ``chat:hist:{user_id}:{thread_id}``.
    Writes refresh the TTL so an active conversation keeps its tail
    around for the full window; idle threads expire naturally without a
    background sweep.
    """

    def __init__(
        self,
        redis: Redis,
        *,
        ttl_seconds: int = DEFAULT_HISTORY_TTL_SECONDS,
        max_turns: int = DEFAULT_HISTORY_MAX_TURNS,
        key_prefix: str = REDIS_THREAD_KEY_PREFIX,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be > 0")
        if max_turns <= 0:
            raise ValueError("max_turns must be > 0")
        self._redis = redis
        self._ttl = int(ttl_seconds)
        self._max_turns = int(max_turns)
        self._prefix = key_prefix.rstrip(":")

    def _key(self, user_id: int, thread_id: str) -> str:
        # ``thread_id`` is caller-controlled — sanitise it lightly so a
        # rogue colon in the id can't escape the namespace.
        safe = str(thread_id).replace("\n", "").replace("\r", "").strip()
        return f"{self._prefix}:{int(user_id)}:{safe or 'default'}"

    async def load(self, user_id: int, thread_id: str) -> list[ChatTurn]:
        raw = await self._redis.get(self._key(user_id, thread_id))
        if not raw:
            return []
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            logger.warning(
                "text.history_decode_failed",
                user_id=user_id,
                thread_id=thread_id,
            )
            return []
        if not isinstance(payload, list):
            return []
        return [ChatTurn.from_dict(item) for item in payload if isinstance(item, dict)]

    async def replace(self, user_id: int, thread_id: str, turns: Sequence[ChatTurn]) -> None:
        trimmed = list(turns)[-self._max_turns :]
        payload = json.dumps([turn.to_dict() for turn in trimmed])
        await self._redis.set(self._key(user_id, thread_id), payload, ex=self._ttl)

    async def append(self, user_id: int, thread_id: str, turns: Sequence[ChatTurn]) -> None:
        existing = await self.load(user_id, thread_id)
        existing.extend(turns)
        await self.replace(user_id, thread_id, existing)

    async def delete(self, user_id: int, thread_id: str) -> None:
        await self._redis.delete(self._key(user_id, thread_id))


class DbConversationHistory:
    """Premium history: durable storage in ``chat_threads`` / ``chat_messages``.

    The implementation flushes its writes but does **not** commit — the
    enclosing request handler controls the outer transaction (same
    pattern as every other service in ``app.services``).

    ``thread_id`` is the caller-controlled external identifier stored on
    ``ChatThread.external_id``; the table's surrogate ``id`` stays
    internal so the API URL surface doesn't leak it.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        max_turns: int = DEFAULT_HISTORY_MAX_TURNS,
    ) -> None:
        if max_turns <= 0:
            raise ValueError("max_turns must be > 0")
        self._session = session
        self._max_turns = int(max_turns)

    async def _get_thread(self, user_id: int, thread_id: str) -> ChatThread | None:
        stmt = select(ChatThread).where(
            ChatThread.user_id == user_id,
            ChatThread.external_id == thread_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def _ensure_thread(self, user_id: int, thread_id: str) -> ChatThread:
        thread = await self._get_thread(user_id, thread_id)
        if thread is not None:
            return thread
        thread = ChatThread(
            user_id=user_id,
            external_id=str(thread_id),
        )
        self._session.add(thread)
        await self._session.flush()
        return thread

    async def load(self, user_id: int, thread_id: str) -> list[ChatTurn]:
        thread = await self._get_thread(user_id, thread_id)
        if thread is None:
            return []
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.thread_id == thread.id)
            .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        turns = [
            ChatTurn(
                role=row.role,
                content=row.content,
                meta=row.metadata_json or None,
                created_at=row.created_at,
            )
            for row in rows
        ]
        return turns[-self._max_turns :]

    async def replace(self, user_id: int, thread_id: str, turns: Sequence[ChatTurn]) -> None:
        """Rewrite the thread's message log to match ``turns``.

        Implemented as ``delete + bulk insert`` — the auto-summariser
        collapses old turns into a single summary row, so a wholesale
        rewrite is the simplest way to keep history consistent without
        diffing.  At realistic thread sizes (<= ``max_turns`` rows) the
        round-trip cost is negligible.
        """
        thread = await self._ensure_thread(user_id, thread_id)
        await self._session.execute(delete(ChatMessage).where(ChatMessage.thread_id == thread.id))
        trimmed = list(turns)[-self._max_turns :]
        last_created: datetime | None = None
        for turn in trimmed:
            content = turn.content
            if len(content) > MAX_MESSAGE_LENGTH:
                content = content[: MAX_MESSAGE_LENGTH - 3] + "..."
            msg = ChatMessage(
                thread_id=thread.id,
                user_id=user_id,
                role=turn.role,
                content=content,
                metadata_json=turn.meta or None,
            )
            self._session.add(msg)
            last_created = turn.created_at or last_created
        thread.message_count = len(trimmed)
        if last_created is not None:
            thread.last_message_at = last_created
        await self._session.flush()

    async def append(self, user_id: int, thread_id: str, turns: Sequence[ChatTurn]) -> None:
        thread = await self._ensure_thread(user_id, thread_id)
        added = 0
        last_created: datetime | None = None
        for turn in turns:
            content = turn.content
            if len(content) > MAX_MESSAGE_LENGTH:
                content = content[: MAX_MESSAGE_LENGTH - 3] + "..."
            self._session.add(
                ChatMessage(
                    thread_id=thread.id,
                    user_id=user_id,
                    role=turn.role,
                    content=content,
                    metadata_json=turn.meta or None,
                )
            )
            added += 1
            last_created = turn.created_at or last_created
        if added:
            thread.message_count = int(thread.message_count or 0) + added
            if last_created is not None:
                thread.last_message_at = last_created
        await self._session.flush()

    async def delete(self, user_id: int, thread_id: str) -> None:
        thread = await self._get_thread(user_id, thread_id)
        if thread is None:
            return
        await self._session.execute(delete(ChatMessage).where(ChatMessage.thread_id == thread.id))
        await self._session.delete(thread)
        await self._session.flush()


# --------------------------------------------------------------- summariser


class SummaryStrategy(Protocol):
    """Hook used by :class:`TextGenerationService` to compact long threads.

    A strategy receives the *full* current history (including the latest
    user prompt) and returns a replacement list — typically a single
    ``summary`` turn followed by the most recent N exchanges.  Returning
    the input unchanged disables summarisation for that call.
    """

    async def maybe_summarise(
        self,
        *,
        user_id: int,
        thread_id: str | None,
        turns: Sequence[ChatTurn],
    ) -> list[ChatTurn]: ...


class HeuristicSummaryStrategy:
    """Cheap built-in summariser used when no explicit strategy is wired.

    Triggers when the thread length crosses ``trigger_turns`` and folds
    the oldest turns into a single ``summary``-role bullet list (no
    Composio call — just truncate-and-stamp).  This lets the
    conversation grow indefinitely without ballooning the prompt token
    count; the API layer can swap in a smarter (provider-backed)
    strategy later by passing one to the service constructor.
    """

    def __init__(
        self,
        *,
        trigger_turns: int = DEFAULT_SUMMARY_TRIGGER_TURNS,
        keep_turns: int = DEFAULT_SUMMARY_KEEP_TURNS,
    ) -> None:
        if trigger_turns <= 0:
            raise ValueError("trigger_turns must be > 0")
        if keep_turns < 0:
            raise ValueError("keep_turns must be >= 0")
        self._trigger = int(trigger_turns)
        self._keep = int(keep_turns)

    async def maybe_summarise(
        self,
        *,
        user_id: int,
        thread_id: str | None,
        turns: Sequence[ChatTurn],
    ) -> list[ChatTurn]:
        msgs = list(turns)
        if len(msgs) < self._trigger:
            return msgs

        # Preserve any pre-existing summary so consecutive summarisations
        # stay monotonic.  Anything in ``older`` is folded into a fresh
        # bullet list; the last ``keep_turns`` user/assistant pairs ride
        # along verbatim for context continuity.
        keep = msgs[-self._keep :] if self._keep else []
        older = msgs[: -self._keep] if self._keep else msgs

        bullets: list[str] = []
        for turn in older:
            if turn.role == ROLE_SUMMARY:
                bullets.append(turn.content.strip())
                continue
            line = turn.content.strip().replace("\n", " ")
            if not line:
                continue
            if len(line) > 200:
                line = line[:197] + "..."
            bullets.append(f"- {turn.role}: {line}")

        summary = ChatTurn(
            role=ROLE_SUMMARY,
            content="\n".join(bullets) or "(empty)",
            created_at=datetime.now(UTC),
        )
        logger.info(
            "text.history_summarised",
            user_id=user_id,
            thread_id=thread_id,
            kept=len(keep),
            folded=len(older),
        )
        return [summary, *keep]


# ------------------------------------------------------------------ service


class TextGenerationService:
    """Service object — instantiate per request with the active session.

    The service is stateless: every call carries its own ``user_id`` and
    parameters so the same instance can serve multiple requests.  Pass
    a :class:`ConversationHistory` to enable thread persistence and an
    optional :class:`SummaryStrategy` to enable auto-summarisation.
    """

    def __init__(
        self,
        session: AsyncSession,
        composio: ComposioClient,
        *,
        history: ConversationHistory | None = None,
        summariser: SummaryStrategy | None = None,
        stream_chunk_size: int = DEFAULT_STREAM_CHUNK_SIZE,
    ) -> None:
        if stream_chunk_size <= 0:
            raise ValueError("stream_chunk_size must be > 0")
        self.session = session
        self.composio = composio
        self.history = history
        self.summariser = summariser or HeuristicSummaryStrategy()
        self._tokens = TokenService(session, get_default_balance_cache())
        self._stream_chunk_size = int(stream_chunk_size)

    # ------------------------------------------------------------------ api

    async def generate(
        self,
        *,
        user_id: int,
        prompt: str,
        mode: str = MODE_BASIC,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        thread_id: str | None = None,
        request_id: str | None = None,
        composio_user_id: str | None = None,
        provider_overrides: dict[str, str] | None = None,
    ) -> TextGenerationResult:
        """Generate one response and debit the per-mode token cost.

        ``thread_id`` activates the configured :class:`ConversationHistory`
        (if any).  When set, the existing turns are loaded, prepended to
        the request, the auto-summariser is consulted and the new
        user/assistant pair is appended on success.

        Raises:
            InvalidPromptError: prompt/system_prompt empty or too long.
            InvalidModeError: unknown mode.
            InvalidTemperatureError: temperature outside ``[0.0, 2.0]``.
            InvalidMaxTokensError: max_tokens outside ``[1, 4096]``.
            InsufficientTokensError: balance below the mode price.
            UserNotFoundError: ``user_id`` does not exist.
            TextProviderError: upstream Composio failure.
        """
        prompt_clean = self._validate_prompt(prompt)
        mode_clean = self._validate_mode(mode)
        system_clean = self._validate_system_prompt(system_prompt)
        temperature_clean = self._validate_temperature(temperature)
        max_tokens_clean = self._validate_max_tokens(max_tokens)
        cost = MODE_COST[mode_clean]

        thread_turns = await self._load_history(user_id, thread_id)
        thread_turns.append(
            ChatTurn(role=ROLE_USER, content=prompt_clean, created_at=datetime.now(UTC))
        )
        thread_turns = await self.summariser.maybe_summarise(
            user_id=user_id, thread_id=thread_id, turns=thread_turns
        )

        request_params: dict[str, Any] = {
            "prompt": prompt_clean,
            "mode": mode_clean,
            "temperature": temperature_clean,
            "max_tokens": max_tokens_clean,
        }
        if system_clean is not None:
            request_params["system_prompt"] = system_clean
        if thread_id:
            request_params["thread_id"] = thread_id

        provider_params: dict[str, Any] = dict(request_params)
        provider_params["messages"] = self._build_messages(
            history=thread_turns, system_prompt=system_clean
        )

        overrides = self._resolve_overrides(mode_clean, provider_overrides)

        spend = await self._tokens.spend(
            user_id=user_id,
            amount=cost,
            service=SERVICE_TYPE,
            request_params=request_params,
            response_status="pending",
        )

        try:
            result = await self._invoke_provider(
                user_id=user_id,
                params=provider_params,
                request_id=request_id,
                composio_user_id=composio_user_id,
                overrides=overrides,
            )
        except TextProviderError:
            await self._refund_spend(
                user_id=user_id,
                transaction_id=spend.transaction_id,
                reason="text provider failed",
            )
            raise

        text = self._extract_text(result)
        if not text:
            await self._refund_spend(
                user_id=user_id,
                transaction_id=spend.transaction_id,
                reason="text provider returned empty result",
            )
            # Audit the failure (zero-cost row) so it surfaces in usage history.
            await log_invocation(
                self.session,
                user_id=user_id,
                result=result,
                tokens_consumed=0,
                request_params=request_params,
            )
            raise TextProviderError(
                "text provider did not return any content",
                provider_error=result.error,
            )

        await self._record_spend_result(
            user_id=user_id,
            usage_log_id=spend.usage_log_id,
            result=result,
        )

        thread_turns.append(
            ChatTurn(role=ROLE_ASSISTANT, content=text, created_at=datetime.now(UTC))
        )
        await self._save_history(user_id, thread_id, thread_turns)

        logger.info(
            "text.generated",
            user_id=user_id,
            mode=mode_clean,
            tokens_spent=cost,
            new_balance=spend.new_balance,
            composio_tool=result.tool,
            mcp_server=result.mcp_server,
            latency_ms=result.latency_ms,
            usage_log_id=spend.usage_log_id,
            transaction_id=spend.transaction_id,
            request_id=request_id,
            thread_id=thread_id,
            history_size=len(thread_turns),
        )

        return TextGenerationResult(
            user_id=user_id,
            prompt=prompt_clean,
            mode=mode_clean,
            text=text,
            tokens_spent=cost,
            new_balance=spend.new_balance,
            composio_tool=result.tool,
            mcp_server=result.mcp_server,
            processing_time_ms=result.latency_ms,
            usage_log_id=spend.usage_log_id,
            transaction_id=spend.transaction_id,
            request_id=request_id,
            thread_id=thread_id,
            history=tuple(thread_turns),
        )

    async def iter_generate(
        self,
        *,
        user_id: int,
        prompt: str,
        mode: str = MODE_BASIC,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        thread_id: str | None = None,
        request_id: str | None = None,
        composio_user_id: str | None = None,
        provider_overrides: dict[str, str] | None = None,
        chunk_size: int | None = None,
    ) -> AsyncIterator[TextChunk]:
        """Stream the response as ``TextChunk`` deltas, then a final marker.

        Composio doesn't expose true SSE streaming yet — this helper
        runs :meth:`generate` synchronously and slices the resulting
        text into evenly-sized chunks so the SSE consumer can render a
        typewriter effect today.  When the upstream client gains real
        streaming, only the body of this method needs to change.
        """
        size = int(chunk_size or self._stream_chunk_size)
        if size <= 0:
            size = self._stream_chunk_size

        result = await self.generate(
            user_id=user_id,
            prompt=prompt,
            mode=mode,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            thread_id=thread_id,
            request_id=request_id,
            composio_user_id=composio_user_id,
            provider_overrides=provider_overrides,
        )

        async def _stream() -> AsyncIterator[TextChunk]:
            for delta in _slice_text(result.text, size):
                yield TextChunk(kind="delta", content=delta)
                # Yield control so the SSE writer can flush each delta
                # before we hand over the next one — keeps the typewriter
                # feel smooth on a single-worker uvicorn.
                await asyncio.sleep(0)
            yield TextChunk(kind="final", content="", result=result)

        return _stream()

    # -------------------------------------------------------------- helpers

    async def _record_spend_result(
        self,
        *,
        user_id: int,
        usage_log_id: int,
        result: ToolResult,
    ) -> None:
        try:
            await self._tokens.record_spend_result(
                usage_log_id=usage_log_id,
                response_status="ok",
                processing_time_ms=result.latency_ms,
                composio_tool=result.tool,
                mcp_server=result.mcp_server,
            )
        except Exception as exc:  # noqa: BLE001 — audit metadata is best-effort
            logger.warning(
                "text.spend_usage_update_failed",
                user_id=user_id,
                usage_log_id=usage_log_id,
                error=str(exc),
            )

    async def _refund_spend(
        self,
        *,
        user_id: int,
        transaction_id: int,
        reason: str,
    ) -> None:
        try:
            await self._tokens.refund(
                transaction_id=transaction_id,
                reason=reason[:100],
            )
        except Exception as exc:  # noqa: BLE001 — preserve the provider error
            logger.warning(
                "text.refund_failed",
                user_id=user_id,
                transaction_id=transaction_id,
                reason=reason,
                error=str(exc),
            )

    async def _invoke_provider(
        self,
        *,
        user_id: int,
        params: dict[str, Any],
        request_id: str | None,
        composio_user_id: str | None,
        overrides: dict[str, str] | None,
    ) -> ToolResult:
        try:
            result = await self.composio.invoke_for_service(
                SERVICE_TYPE,
                params,
                user_id=composio_user_id,
                request_id=request_id,
                metadata={"app_user_id": str(user_id)},
                overrides=overrides,
            )
        except ComposioError as exc:
            logger.warning(
                "text.composio_failed",
                user_id=user_id,
                error=str(exc),
                request_id=request_id,
            )
            raise TextProviderError(
                "text provider call failed",
                provider_error=str(exc),
            ) from exc

        if not result.successful:
            logger.warning(
                "text.composio_unsuccessful",
                user_id=user_id,
                tool=result.tool,
                error=result.error,
                request_id=request_id,
            )
            raise TextProviderError(
                f"text provider returned unsuccessful: {result.error or 'unknown'}",
                provider_error=result.error,
            )
        return result

    async def _load_history(self, user_id: int, thread_id: str | None) -> list[ChatTurn]:
        if self.history is None or not thread_id:
            return []
        try:
            return await self.history.load(user_id, thread_id)
        except Exception as exc:  # noqa: BLE001 — history is best-effort
            logger.warning(
                "text.history_load_failed",
                user_id=user_id,
                thread_id=thread_id,
                error=str(exc),
            )
            return []

    async def _save_history(
        self,
        user_id: int,
        thread_id: str | None,
        turns: Sequence[ChatTurn],
    ) -> None:
        if self.history is None or not thread_id:
            return
        try:
            await self.history.replace(user_id, thread_id, turns)
        except Exception as exc:  # noqa: BLE001 — history is best-effort
            logger.warning(
                "text.history_save_failed",
                user_id=user_id,
                thread_id=thread_id,
                error=str(exc),
            )

    @staticmethod
    def _build_messages(
        *,
        history: Sequence[ChatTurn],
        system_prompt: str | None,
    ) -> list[dict[str, str]]:
        """Render the chat history into the OpenAI/Anthropic ``messages`` shape.

        ``summary`` turns are flattened to ``system`` so downstream
        providers that don't know our internal role survive the round
        trip.  ``system_prompt`` (when set) is always the first message
        so it can't be drowned out by a later summary.
        """
        out: list[dict[str, str]] = []
        if system_prompt:
            out.append({"role": ROLE_SYSTEM, "content": system_prompt})
        for turn in history:
            role = turn.role
            if role == ROLE_SUMMARY:
                role = ROLE_SYSTEM
            elif role not in {ROLE_SYSTEM, ROLE_USER, ROLE_ASSISTANT}:
                role = ROLE_USER
            content = turn.content
            if len(content) > MAX_MESSAGE_LENGTH:
                content = content[: MAX_MESSAGE_LENGTH - 3] + "..."
            out.append({"role": role, "content": content})
        return out

    @staticmethod
    def _extract_text(result: ToolResult) -> str:
        """Pull the assistant message out of a Composio response.

        Toolkits aren't fully aligned yet — Gemini returns ``text``,
        Claude / OpenAI return ``message.content`` or ``choices[0].
        message.content``.  We try the documented keys in order and fall
        back to scanning ``output_text`` (Composio's normalised field).
        """
        data = result.data or {}
        for key in ("text", "output_text", "result", "answer", "response"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        message = data.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
            if isinstance(content, list):
                joined = _join_content_parts(content)
                if joined:
                    return joined

        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                msg = first.get("message")
                if isinstance(msg, dict):
                    content = msg.get("content")
                    if isinstance(content, str) and content.strip():
                        return content.strip()
                    if isinstance(content, list):
                        joined = _join_content_parts(content)
                        if joined:
                            return joined
                text = first.get("text")
                if isinstance(text, str) and text.strip():
                    return text.strip()
        return ""

    @staticmethod
    def _resolve_overrides(
        mode: str, caller_overrides: dict[str, str] | None
    ) -> dict[str, str] | None:
        """Compose the Composio routing override for ``mode``.

        Caller-provided ``provider_overrides`` win over the mode default
        so admins can pin a single mode without re-deploying.
        """
        toolkit = MODE_TOOLKIT.get(mode)
        out: dict[str, str] = {}
        if toolkit:
            out[SERVICE_TYPE] = toolkit
        if caller_overrides:
            out.update(caller_overrides)
        return out or None

    # --------------------------------------------------------------- validators

    @staticmethod
    def _validate_prompt(prompt: str) -> str:
        if prompt is None:
            raise InvalidPromptError("prompt is required")
        clean = str(prompt).strip()
        if not clean:
            raise InvalidPromptError("prompt is required")
        if len(clean) > MAX_PROMPT_LENGTH:
            raise InvalidPromptError(f"prompt must be at most {MAX_PROMPT_LENGTH} characters")
        return clean

    @staticmethod
    def _validate_system_prompt(value: str | None) -> str | None:
        if value is None:
            return None
        clean = str(value).strip()
        if not clean:
            return None
        if len(clean) > MAX_SYSTEM_PROMPT_LENGTH:
            raise InvalidPromptError(
                f"system_prompt must be at most {MAX_SYSTEM_PROMPT_LENGTH} characters"
            )
        return clean

    @staticmethod
    def _validate_mode(mode: str) -> str:
        if mode is None:
            raise InvalidModeError("mode is required")
        clean = str(mode).strip().lower()
        if clean not in SUPPORTED_MODES:
            raise InvalidModeError(f"mode must be one of {sorted(SUPPORTED_MODES)}")
        return clean

    @staticmethod
    def _validate_temperature(value: float | None) -> float:
        if value is None:
            return DEFAULT_TEMPERATURE
        try:
            num = float(value)
        except (TypeError, ValueError) as exc:
            raise InvalidTemperatureError("temperature must be a number") from exc
        if num < MIN_TEMPERATURE or num > MAX_TEMPERATURE:
            raise InvalidTemperatureError(
                f"temperature must be between {MIN_TEMPERATURE} and {MAX_TEMPERATURE}"
            )
        return num

    @staticmethod
    def _validate_max_tokens(value: int | None) -> int:
        if value is None:
            return DEFAULT_MAX_TOKENS
        try:
            num = int(value)
        except (TypeError, ValueError) as exc:
            raise InvalidMaxTokensError("max_tokens must be an integer") from exc
        if num < MIN_MAX_TOKENS or num > MAX_MAX_TOKENS:
            raise InvalidMaxTokensError(
                f"max_tokens must be between {MIN_MAX_TOKENS} and {MAX_MAX_TOKENS}"
            )
        return num


# --------------------------------------------------------------- module helpers


def _join_content_parts(parts: list[Any]) -> str:
    """Flatten Anthropic-style content blocks into a single string."""
    chunks: list[str] = []
    for part in parts:
        if isinstance(part, str):
            chunks.append(part)
        elif isinstance(part, dict):
            value = part.get("text") or part.get("content")
            if isinstance(value, str):
                chunks.append(value)
    return "\n".join(c for c in (c.strip() for c in chunks) if c)


_WORD_SPLIT = re.compile(r"(\s+)")


def _slice_text(text: str, size: int) -> list[str]:
    """Slice ``text`` into ~``size``-char chunks aligned to word boundaries.

    Falls back to fixed-width slicing when the text contains no spaces.
    Empty input yields ``[""]`` so the streamer still emits one delta —
    keeping the SSE shape consistent with non-empty responses.
    """
    if not text:
        return [""]
    if size <= 0:
        return [text]

    pieces = [p for p in _WORD_SPLIT.split(text) if p != ""]
    if not pieces:
        return [text[i : i + size] for i in range(0, len(text), size)]

    chunks: list[str] = []
    buf = ""
    for piece in pieces:
        if len(buf) + len(piece) > size and buf:
            chunks.append(buf)
            buf = piece
        else:
            buf += piece
    if buf:
        chunks.append(buf)
    return chunks


__all__ = [
    "ChatTurn",
    "ConversationHistory",
    "DbConversationHistory",
    "DEFAULT_HISTORY_MAX_TURNS",
    "DEFAULT_HISTORY_TTL_SECONDS",
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_STREAM_CHUNK_SIZE",
    "DEFAULT_SUMMARY_KEEP_TURNS",
    "DEFAULT_SUMMARY_TRIGGER_TURNS",
    "DEFAULT_TEMPERATURE",
    "HeuristicSummaryStrategy",
    "InvalidMaxTokensError",
    "InvalidModeError",
    "InvalidPromptError",
    "InvalidTemperatureError",
    "MAX_MAX_TOKENS",
    "MAX_PROMPT_LENGTH",
    "MAX_SYSTEM_PROMPT_LENGTH",
    "MAX_TEMPERATURE",
    "MIN_MAX_TOKENS",
    "MIN_TEMPERATURE",
    "MODE_AGENT",
    "MODE_ADVANCED",
    "MODE_BASIC",
    "MODE_COST",
    "MODE_TOOLKIT",
    "REDIS_THREAD_KEY_PREFIX",
    "RedisConversationHistory",
    "ROLE_ASSISTANT",
    "ROLE_SUMMARY",
    "ROLE_SYSTEM",
    "ROLE_USER",
    "SERVICE_TYPE",
    "SUPPORTED_MODES",
    "SummaryStrategy",
    "TextChunk",
    "TextGenerationError",
    "TextGenerationResult",
    "TextGenerationService",
    "TextProviderError",
]
