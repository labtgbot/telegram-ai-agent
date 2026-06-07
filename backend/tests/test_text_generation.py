"""Unit tests for :class:`TextGenerationService`.

The service runs against :class:`MockComposioClient` plus an in-memory
stub for the SQLAlchemy session / :class:`TokenService` so the suite
runs without a database or a real Redis.

Coverage:

* mode-cost table (basic=1, advanced=5, autonomous_agent=10) and
  ``SERVICE_TYPE`` constant match the issue spec;
* validation of ``prompt`` / ``system_prompt`` / ``mode`` /
  ``temperature`` / ``max_tokens`` (boundaries + invalid types);
* debit-first accounting surfaces :class:`InsufficientTokensError`
  before any provider call;
* per-mode toolkit override resolves to the right Composio tool;
* response-text extraction across the assorted Composio response shapes
  (``text``, ``output_text``, ``message.content``,
  ``choices[0].message.content``, Anthropic content blocks);
* failure paths: provider exception, ``successful=False`` payload,
  empty-content response — each translated to
  :class:`TextProviderError` and audited with a zero-cost row;
* conversation-history round-trip: when a :class:`ConversationHistory`
  is supplied the existing turns are loaded, the new user/assistant
  pair is appended, and the auto-summariser collapses long threads;
* :meth:`iter_generate` produces ``delta`` chunks followed by a single
  ``final`` chunk carrying the :class:`TextGenerationResult`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from app.services.composio import (
    ComposioTransientError,
    MockComposioClient,
    ToolInvocation,
    ToolResult,
)
from app.services.text_generation import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
    MAX_MAX_TOKENS,
    MAX_PROMPT_LENGTH,
    MAX_SYSTEM_PROMPT_LENGTH,
    MAX_TEMPERATURE,
    MIN_MAX_TOKENS,
    MODE_ADVANCED,
    MODE_AGENT,
    MODE_BASIC,
    MODE_COST,
    MODE_TOOLKIT,
    ROLE_ASSISTANT,
    ROLE_SUMMARY,
    ROLE_USER,
    SERVICE_TYPE,
    SUPPORTED_MODES,
    ChatTurn,
    HeuristicSummaryStrategy,
    InvalidMaxTokensError,
    InvalidModeError,
    InvalidPromptError,
    InvalidTemperatureError,
    TextChunk,
    TextGenerationResult,
    TextGenerationService,
    TextProviderError,
)
from app.services.token_service import (
    InsufficientTokensError,
    SpendResult,
    TokenOperationResult,
    UserNotFoundError,
)

# --------------------------------------------------------------- stubs


@dataclass
class _RecordedSpend:
    transaction_id: int
    usage_log_id: int
    user_id: int
    amount: int
    service: str
    request_params: dict[str, Any] | None
    response_status: str | None
    processing_time_ms: int | None
    composio_tool: str | None
    mcp_server: str | None


@dataclass
class _RecordedRefund:
    transaction_id: int
    reason: str | None


class _FakeTokenService:
    """Stand-in for :class:`TokenService` that doesn't touch a DB."""

    def __init__(self, *, balances: dict[int, int] | None = None) -> None:
        self.balances: dict[int, int] = dict(balances or {})
        self.spends: list[_RecordedSpend] = []
        self.refunds: list[_RecordedRefund] = []
        self.balance_calls: list[int] = []
        self._next_tx = 1000
        self._next_log = 5000

    async def get_balance(self, user_id: int) -> int:
        self.balance_calls.append(user_id)
        if user_id not in self.balances:
            raise UserNotFoundError(f"user {user_id} not found")
        return self.balances[user_id]

    async def spend(
        self,
        *,
        user_id: int,
        amount: int,
        service: str,
        request_params: dict[str, Any] | None = None,
        response_status: str | None = "ok",
        processing_time_ms: int | None = None,
        composio_tool: str | None = None,
        mcp_server: str | None = None,
    ) -> SpendResult:
        if user_id not in self.balances:
            raise UserNotFoundError(f"user {user_id} not found")
        current = self.balances[user_id]
        if current < amount:
            raise InsufficientTokensError(required=amount, available=current)
        self.balances[user_id] = current - amount
        self._next_tx += 1
        self._next_log += 1
        transaction_id = self._next_tx
        usage_log_id = self._next_log
        self.spends.append(
            _RecordedSpend(
                transaction_id=transaction_id,
                usage_log_id=usage_log_id,
                user_id=user_id,
                amount=amount,
                service=service,
                request_params=dict(request_params or {}),
                response_status=response_status,
                processing_time_ms=processing_time_ms,
                composio_tool=composio_tool,
                mcp_server=mcp_server,
            )
        )
        return SpendResult(
            user_id=user_id,
            amount=amount,
            new_balance=self.balances[user_id],
            transaction_id=transaction_id,
            transaction_type="spend",
            usage_log_id=usage_log_id,
        )

    async def record_spend_result(
        self,
        *,
        usage_log_id: int,
        response_status: str | None,
        processing_time_ms: int | None = None,
        composio_tool: str | None = None,
        mcp_server: str | None = None,
        request_params: dict[str, Any] | None = None,
    ) -> None:
        spend = next((s for s in self.spends if s.usage_log_id == usage_log_id), None)
        if spend is None:
            return
        spend.response_status = response_status
        spend.processing_time_ms = processing_time_ms
        spend.composio_tool = composio_tool
        spend.mcp_server = mcp_server
        if request_params is not None:
            spend.request_params = dict(request_params)

    async def refund(
        self,
        *,
        transaction_id: int,
        reason: str | None = None,
    ) -> TokenOperationResult:
        self.refunds.append(_RecordedRefund(transaction_id=transaction_id, reason=reason))
        spend = next((s for s in self.spends if s.transaction_id == transaction_id), None)
        if spend is None:
            raise RuntimeError("no matching spend to refund in fake service")
        self.balances[spend.user_id] += spend.amount
        self._next_tx += 1
        return TokenOperationResult(
            user_id=spend.user_id,
            amount=spend.amount,
            new_balance=self.balances[spend.user_id],
            transaction_id=self._next_tx,
            transaction_type="refund",
        )


class _FakeSession:
    """Minimal AsyncSession stub — collects audit rows added via ``add``."""

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.flushes = 0

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushes += 1


@dataclass
class _FakeHistory:
    """In-memory :class:`ConversationHistory` for tests.

    Records every load / append / replace call so tests can assert the
    full history round-trip without spinning up Redis or Postgres.
    """

    initial: list[ChatTurn] = field(default_factory=list)
    loads: list[tuple[int, str]] = field(default_factory=list)
    replaces: list[tuple[int, str, list[ChatTurn]]] = field(default_factory=list)
    appends: list[tuple[int, str, list[ChatTurn]]] = field(default_factory=list)
    deletes: list[tuple[int, str]] = field(default_factory=list)

    async def load(self, user_id: int, thread_id: str) -> list[ChatTurn]:
        self.loads.append((user_id, thread_id))
        return list(self.initial)

    async def replace(self, user_id: int, thread_id: str, turns: list[ChatTurn]) -> None:
        self.replaces.append((user_id, thread_id, list(turns)))
        self.initial = list(turns)

    async def append(self, user_id: int, thread_id: str, turns: list[ChatTurn]) -> None:
        self.appends.append((user_id, thread_id, list(turns)))
        self.initial = list(self.initial) + list(turns)

    async def delete(self, user_id: int, thread_id: str) -> None:
        self.deletes.append((user_id, thread_id))
        self.initial = []


@pytest.fixture
def fake_tokens() -> _FakeTokenService:
    return _FakeTokenService(balances={42: 500})


@pytest.fixture
def fake_session() -> _FakeSession:
    return _FakeSession()


@pytest.fixture
def composio_mock() -> MockComposioClient:
    return MockComposioClient()


def _build_service(
    session: _FakeSession,
    composio: MockComposioClient,
    tokens: _FakeTokenService,
    *,
    history: Any | None = None,
    summariser: Any | None = None,
    stream_chunk_size: int = 64,
) -> TextGenerationService:
    service = TextGenerationService(
        session,  # type: ignore[arg-type]
        composio,  # type: ignore[arg-type]
        history=history,
        summariser=summariser,
        stream_chunk_size=stream_chunk_size,
    )
    # Swap the real ``TokenService`` (which needs a DB) for the in-memory stub.
    service._tokens = tokens  # type: ignore[assignment]
    return service


# --------------------------------------------------------------- constants


def test_mode_cost_table_matches_spec() -> None:
    assert MODE_COST == {
        MODE_BASIC: 1,
        MODE_ADVANCED: 5,
        MODE_AGENT: 10,
    }


def test_service_type_is_text() -> None:
    assert SERVICE_TYPE == "text"


def test_mode_toolkit_routes_to_distinct_providers() -> None:
    assert MODE_TOOLKIT[MODE_BASIC] == "gemini"
    assert MODE_TOOLKIT[MODE_ADVANCED] == "claude"
    assert MODE_TOOLKIT[MODE_AGENT] == "openai_gpt"


def test_supported_modes_covers_mode_cost() -> None:
    assert frozenset(MODE_COST.keys()) == SUPPORTED_MODES


# ------------------------------------------------------------- validation


@pytest.mark.asyncio
async def test_rejects_empty_prompt(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    service = _build_service(fake_session, composio_mock, fake_tokens)
    with pytest.raises(InvalidPromptError):
        await service.generate(user_id=42, prompt="   ")
    # No composio call should have been issued.
    assert composio_mock.calls == []


@pytest.mark.asyncio
async def test_rejects_none_prompt(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    service = _build_service(fake_session, composio_mock, fake_tokens)
    with pytest.raises(InvalidPromptError):
        await service.generate(user_id=42, prompt=None)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_rejects_overlong_prompt(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    service = _build_service(fake_session, composio_mock, fake_tokens)
    with pytest.raises(InvalidPromptError):
        await service.generate(user_id=42, prompt="a" * (MAX_PROMPT_LENGTH + 1))


@pytest.mark.asyncio
async def test_rejects_overlong_system_prompt(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    service = _build_service(fake_session, composio_mock, fake_tokens)
    with pytest.raises(InvalidPromptError):
        await service.generate(
            user_id=42,
            prompt="hi",
            system_prompt="x" * (MAX_SYSTEM_PROMPT_LENGTH + 1),
        )


@pytest.mark.asyncio
async def test_rejects_unknown_mode(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    service = _build_service(fake_session, composio_mock, fake_tokens)
    with pytest.raises(InvalidModeError):
        await service.generate(user_id=42, prompt="hi", mode="legendary")


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_value", [-0.1, MAX_TEMPERATURE + 0.1, "warm"])
async def test_rejects_out_of_range_temperature(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
    bad_value: Any,
) -> None:
    service = _build_service(fake_session, composio_mock, fake_tokens)
    with pytest.raises(InvalidTemperatureError):
        await service.generate(user_id=42, prompt="hi", temperature=bad_value)


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_value", [MIN_MAX_TOKENS - 1, MAX_MAX_TOKENS + 1, "lots"])
async def test_rejects_out_of_range_max_tokens(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
    bad_value: Any,
) -> None:
    service = _build_service(fake_session, composio_mock, fake_tokens)
    with pytest.raises(InvalidMaxTokensError):
        await service.generate(user_id=42, prompt="hi", max_tokens=bad_value)


# ------------------------------------------------------------- happy path


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,expected_cost,expected_tool",
    [
        (MODE_BASIC, 1, "gemini"),
        (MODE_ADVANCED, 5, "claude"),
        (MODE_AGENT, 10, "openai_gpt"),
    ],
)
async def test_generate_debits_correct_cost_per_mode(
    fake_session: _FakeSession,
    fake_tokens: _FakeTokenService,
    mode: str,
    expected_cost: int,
    expected_tool: str,
) -> None:
    composio_mock = MockComposioClient()
    composio_mock.set_response(expected_tool, data={"text": "an answer"})
    service = _build_service(fake_session, composio_mock, fake_tokens)

    outcome = await service.generate(user_id=42, prompt="what is 2+2?", mode=mode)

    assert isinstance(outcome, TextGenerationResult)
    assert outcome.mode == mode
    assert outcome.tokens_spent == expected_cost
    assert outcome.new_balance == 500 - expected_cost
    assert outcome.text == "an answer"
    assert outcome.composio_tool == expected_tool
    assert outcome.usage_log_id > 0
    assert outcome.transaction_id > 0

    # Per-mode toolkit override must reach the mock client.
    assert len(composio_mock.calls) == 1
    assert composio_mock.calls[0].tool == expected_tool


@pytest.mark.asyncio
async def test_generate_passes_request_params_to_composio(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock.set_response("gemini", data={"text": "hi back"})
    service = _build_service(fake_session, composio_mock, fake_tokens)

    await service.generate(
        user_id=42,
        prompt="  hello  ",
        mode=MODE_BASIC,
        system_prompt=" be terse ",
        temperature=0.25,
        max_tokens=128,
        thread_id="thread-1",
        request_id="req-1",
    )

    assert len(composio_mock.calls) == 1
    call: ToolInvocation = composio_mock.calls[0]
    assert call.tool == "gemini"
    assert call.service_type == "text"
    assert call.request_id == "req-1"
    assert call.metadata == {"app_user_id": "42"}
    # Validated / trimmed values reach the provider verbatim, plus the
    # ``messages`` payload assembled from history + system prompt.
    assert call.params["prompt"] == "hello"
    assert call.params["mode"] == MODE_BASIC
    assert call.params["temperature"] == 0.25
    assert call.params["max_tokens"] == 128
    assert call.params["system_prompt"] == "be terse"
    assert call.params["thread_id"] == "thread-1"
    messages = call.params["messages"]
    assert messages[0] == {"role": "system", "content": "be terse"}
    assert messages[-1] == {"role": "user", "content": "hello"}


@pytest.mark.asyncio
async def test_generate_uses_defaults_when_omitted(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock.set_response("gemini", data={"text": "hi"})
    service = _build_service(fake_session, composio_mock, fake_tokens)
    await service.generate(user_id=42, prompt="hi")

    call = composio_mock.calls[0]
    assert call.params["temperature"] == DEFAULT_TEMPERATURE
    assert call.params["max_tokens"] == DEFAULT_MAX_TOKENS
    # ``system_prompt`` / ``thread_id`` are absent when not supplied.
    assert "system_prompt" not in call.params
    assert "thread_id" not in call.params


@pytest.mark.asyncio
async def test_generate_records_spend_with_audit_metadata(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock.set_response(
        "gemini",
        data={"text": "ok"},
        mcp_server="composio-prod-1",
    )
    service = _build_service(fake_session, composio_mock, fake_tokens)

    await service.generate(user_id=42, prompt="hello", mode=MODE_BASIC)

    assert len(fake_tokens.spends) == 1
    spend = fake_tokens.spends[0]
    assert spend.user_id == 42
    assert spend.amount == 1
    assert spend.service == "text"
    assert spend.response_status == "ok"
    assert spend.composio_tool == "gemini"
    assert spend.mcp_server == "composio-prod-1"
    assert spend.request_params is not None
    assert spend.request_params["prompt"] == "hello"
    assert spend.request_params["mode"] == MODE_BASIC


@pytest.mark.asyncio
async def test_caller_overrides_win_over_mode_default(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    """Admins can repoint a mode at a different toolkit without redeploy."""
    composio_mock.set_response("claude", data={"text": "answer via claude"})
    service = _build_service(fake_session, composio_mock, fake_tokens)

    outcome = await service.generate(
        user_id=42,
        prompt="hello",
        mode=MODE_BASIC,
        provider_overrides={"text": "claude"},
    )

    assert outcome.composio_tool == "claude"
    assert composio_mock.calls[0].tool == "claude"


# ---------------------------------------------------- response shape extraction


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"text": "plain text"}, "plain text"),
        ({"output_text": "normalised"}, "normalised"),
        ({"result": "via result"}, "via result"),
        ({"answer": "via answer"}, "via answer"),
        ({"response": "via response"}, "via response"),
        ({"message": {"content": "via msg"}}, "via msg"),
        (
            {
                "message": {
                    "content": [
                        {"text": "block one"},
                        {"text": "block two"},
                    ]
                }
            },
            "block one\nblock two",
        ),
        (
            {"choices": [{"message": {"content": "choices content"}}]},
            "choices content",
        ),
        (
            {"choices": [{"text": "choices text"}]},
            "choices text",
        ),
    ],
)
async def test_generate_handles_various_response_shapes(
    fake_session: _FakeSession,
    fake_tokens: _FakeTokenService,
    payload: dict[str, Any],
    expected: str,
) -> None:
    composio_mock = MockComposioClient()
    composio_mock.set_response("gemini", data=payload)
    service = _build_service(fake_session, composio_mock, fake_tokens)

    outcome = await service.generate(user_id=42, prompt="hi")
    assert outcome.text == expected


# --------------------------------------------------------- balance + provider


@pytest.mark.asyncio
async def test_insufficient_balance_is_raised_before_provider_call(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
) -> None:
    tokens = _FakeTokenService(balances={42: 2})
    composio_mock.set_response("openai_gpt", data={"text": "ok"})
    service = _build_service(fake_session, composio_mock, tokens)

    with pytest.raises(InsufficientTokensError) as exc:
        # MODE_AGENT costs 10; balance is 2.
        await service.generate(user_id=42, prompt="hi", mode=MODE_AGENT)

    assert exc.value.required == 10
    assert exc.value.available == 2
    # Provider must NOT have been called and no spend recorded.
    assert composio_mock.calls == []
    assert tokens.spends == []
    assert tokens.balances[42] == 2


@pytest.mark.asyncio
async def test_unknown_user_raises_user_not_found(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
) -> None:
    tokens = _FakeTokenService(balances={})  # no users
    service = _build_service(fake_session, composio_mock, tokens)
    with pytest.raises(UserNotFoundError):
        await service.generate(user_id=999, prompt="hi")


@pytest.mark.asyncio
async def test_provider_error_is_translated_and_does_not_debit(
    fake_session: _FakeSession,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock = MockComposioClient()
    composio_mock.set_error("gemini", ComposioTransientError("upstream 503"))
    service = _build_service(fake_session, composio_mock, fake_tokens)

    with pytest.raises(TextProviderError) as exc:
        await service.generate(user_id=42, prompt="hi")
    assert "text provider call failed" in str(exc.value)
    assert exc.value.provider_error is not None
    # Balance returns to its original value after the refund.
    assert len(fake_tokens.spends) == 1
    assert len(fake_tokens.refunds) == 1
    assert fake_tokens.balances[42] == 500


@pytest.mark.asyncio
async def test_unsuccessful_provider_response_is_translated(
    fake_session: _FakeSession,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock = MockComposioClient()
    composio_mock.set_response(
        "gemini",
        successful=False,
        data={"text": "ignored"},
        error="moderation_blocked",
    )
    service = _build_service(fake_session, composio_mock, fake_tokens)

    with pytest.raises(TextProviderError) as exc:
        await service.generate(user_id=42, prompt="hi")
    assert exc.value.provider_error == "moderation_blocked"
    assert len(fake_tokens.spends) == 1
    assert len(fake_tokens.refunds) == 1
    assert fake_tokens.balances[42] == 500


@pytest.mark.asyncio
async def test_empty_response_audits_failure_and_raises(
    fake_session: _FakeSession,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock = MockComposioClient()
    composio_mock.set_response("gemini", data={"unexpected": "shape"})
    service = _build_service(fake_session, composio_mock, fake_tokens)

    with pytest.raises(TextProviderError):
        await service.generate(user_id=42, prompt="hi")

    # ``log_invocation`` writes a TokenUsageLog row directly via session.add
    # so the audit row should be present in our fake session.
    assert len(fake_session.added) >= 1
    assert fake_session.flushes >= 1
    # The debit is refunded, so the failure path has no net charge.
    assert len(fake_tokens.spends) == 1
    assert len(fake_tokens.refunds) == 1
    assert fake_tokens.balances[42] == 500


# ----------------------------------------------------- conversation history


@pytest.mark.asyncio
async def test_history_load_save_round_trip(
    fake_session: _FakeSession,
    fake_tokens: _FakeTokenService,
) -> None:
    """When ``thread_id`` is set, history is loaded, sent to the provider
    and the new user/assistant pair is persisted back."""
    composio_mock = MockComposioClient()
    composio_mock.set_response("gemini", data={"text": "second answer"})
    history = _FakeHistory(
        initial=[
            ChatTurn(role=ROLE_USER, content="first question"),
            ChatTurn(role=ROLE_ASSISTANT, content="first answer"),
        ]
    )
    service = _build_service(fake_session, composio_mock, fake_tokens, history=history)

    outcome = await service.generate(
        user_id=42,
        prompt="second question",
        mode=MODE_BASIC,
        thread_id="t-1",
    )
    assert outcome.text == "second answer"

    # ``load`` was called exactly once.
    assert history.loads == [(42, "t-1")]

    # The provider received the entire conversation so far + the new prompt.
    call = composio_mock.calls[0]
    messages = call.params["messages"]
    assert [m["content"] for m in messages] == [
        "first question",
        "first answer",
        "second question",
    ]
    assert [m["role"] for m in messages] == [
        "user",
        "assistant",
        "user",
    ]

    # ``replace`` was called once with the appended assistant turn.
    assert len(history.replaces) == 1
    _, saved_thread_id, saved_turns = history.replaces[0]
    assert saved_thread_id == "t-1"
    contents = [t.content for t in saved_turns]
    roles = [t.role for t in saved_turns]
    assert contents == [
        "first question",
        "first answer",
        "second question",
        "second answer",
    ]
    assert roles == [ROLE_USER, ROLE_ASSISTANT, ROLE_USER, ROLE_ASSISTANT]


@pytest.mark.asyncio
async def test_history_load_failure_is_swallowed(
    fake_session: _FakeSession,
    fake_tokens: _FakeTokenService,
) -> None:
    """History is best-effort — a backend error doesn't fail the request."""
    composio_mock = MockComposioClient()
    composio_mock.set_response("gemini", data={"text": "ok"})

    class _BrokenHistory:
        async def load(self, *_a: Any, **_k: Any) -> list[ChatTurn]:
            raise RuntimeError("redis unreachable")

        async def replace(self, *_a: Any, **_k: Any) -> None:
            return None

        async def append(self, *_a: Any, **_k: Any) -> None:
            return None

        async def delete(self, *_a: Any, **_k: Any) -> None:
            return None

    service = _build_service(fake_session, composio_mock, fake_tokens, history=_BrokenHistory())
    outcome = await service.generate(user_id=42, prompt="hi", thread_id="t-1")
    assert outcome.text == "ok"
    # The provider still saw the prompt even though history failed to load.
    messages = composio_mock.calls[0].params["messages"]
    assert messages[-1] == {"role": "user", "content": "hi"}


@pytest.mark.asyncio
async def test_history_disabled_without_thread_id(
    fake_session: _FakeSession,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock = MockComposioClient()
    composio_mock.set_response("gemini", data={"text": "ok"})
    history = _FakeHistory()
    service = _build_service(fake_session, composio_mock, fake_tokens, history=history)

    await service.generate(user_id=42, prompt="hi")  # no thread_id

    assert history.loads == []
    assert history.replaces == []
    assert history.appends == []


# ------------------------------------------------------------- summariser


@pytest.mark.asyncio
async def test_summariser_collapses_long_threads(
    fake_session: _FakeSession,
    fake_tokens: _FakeTokenService,
) -> None:
    """Once the history crosses the trigger, older turns fold into one
    ``summary`` row so the prompt stays small."""
    composio_mock = MockComposioClient()
    composio_mock.set_response("gemini", data={"text": "fresh answer"})

    # Build a 20-turn history (10 user/assistant pairs).
    initial: list[ChatTurn] = []
    for i in range(10):
        initial.append(
            ChatTurn(
                role=ROLE_USER,
                content=f"question {i}",
                created_at=datetime.now(UTC),
            )
        )
        initial.append(
            ChatTurn(
                role=ROLE_ASSISTANT,
                content=f"answer {i}",
                created_at=datetime.now(UTC),
            )
        )
    history = _FakeHistory(initial=initial)
    # Trigger summarisation aggressively so the test is deterministic.
    summariser = HeuristicSummaryStrategy(trigger_turns=4, keep_turns=2)
    service = _build_service(
        fake_session,
        composio_mock,
        fake_tokens,
        history=history,
        summariser=summariser,
    )

    await service.generate(
        user_id=42,
        prompt="new question",
        mode=MODE_BASIC,
        thread_id="t-long",
    )

    # The provider's messages must include a leading system-shaped summary
    # (HeuristicSummaryStrategy emits ROLE_SUMMARY which the service maps
    # to ``system`` for downstream providers).
    messages = composio_mock.calls[0].params["messages"]
    assert messages[0]["role"] == "system"
    assert messages[0]["content"]  # non-empty bullet list
    # Plus the last few turns + the brand-new user prompt.
    assert messages[-1] == {"role": "user", "content": "new question"}
    # The complete message list is much shorter than the original 21 turns.
    assert len(messages) <= 5

    # The saved history reflects the summarisation, not the raw 20+ turns.
    saved = history.replaces[-1][2]
    assert any(t.role == ROLE_SUMMARY for t in saved)
    assert len(saved) <= summariser._keep + 1 + 2  # summary + keep + new pair


# ----------------------------------------------------------------- streaming


@pytest.mark.asyncio
async def test_iter_generate_emits_deltas_then_final(
    fake_session: _FakeSession,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock = MockComposioClient()
    composio_mock.set_response(
        "gemini",
        data={"text": "the quick brown fox jumps over the lazy dog"},
    )
    service = _build_service(
        fake_session,
        composio_mock,
        fake_tokens,
        stream_chunk_size=8,
    )

    stream = await service.iter_generate(
        user_id=42,
        prompt="tell me a story",
        mode=MODE_BASIC,
    )

    chunks: list[TextChunk] = []
    async for chunk in stream:
        chunks.append(chunk)

    # At least one delta plus the terminal ``final`` chunk.
    assert any(c.kind == "delta" for c in chunks)
    assert chunks[-1].kind == "final"
    assert chunks[-1].result is not None
    assert chunks[-1].result.text == "the quick brown fox jumps over the lazy dog"
    # Accumulated deltas reconstruct the full text.
    rebuilt = "".join(c.content for c in chunks if c.kind == "delta")
    assert rebuilt == "the quick brown fox jumps over the lazy dog"
    # Tokens were spent exactly once (the streaming wrapper is built on
    # top of ``generate``).
    assert len(fake_tokens.spends) == 1
    assert fake_tokens.spends[0].amount == MODE_COST[MODE_BASIC]


@pytest.mark.asyncio
async def test_iter_generate_surfaces_validation_before_streaming(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    """Invalid input must raise from the *call* to ``iter_generate``, not
    from the returned iterator, so the API layer can map it to a 4xx
    before opening an SSE response."""
    service = _build_service(fake_session, composio_mock, fake_tokens)
    with pytest.raises(InvalidPromptError):
        await service.iter_generate(user_id=42, prompt="   ")
    assert composio_mock.calls == []


# --------------------------------------------------------- handler dispatch


@pytest.mark.asyncio
async def test_handler_overrides_response_per_invocation(
    fake_session: _FakeSession,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock = MockComposioClient()

    async def dynamic(invocation: ToolInvocation) -> ToolResult:
        prompt = invocation.params["prompt"]
        return ToolResult(
            tool=invocation.tool,
            successful=True,
            data={"text": f"echo: {prompt}"},
        )

    composio_mock.set_handler("gemini", dynamic)
    service = _build_service(fake_session, composio_mock, fake_tokens)

    outcome = await service.generate(user_id=42, prompt="bonjour")
    assert outcome.text == "echo: bonjour"
