"""Unit tests for :class:`ImageGenerationService`.

The service is exercised against :class:`MockComposioClient` plus an
in-memory stub for the SQLAlchemy session / :class:`TokenService` so
the suite runs without a database.

Pure-unit coverage focuses on:

* validation of ``quality``, ``aspect_ratio``, ``prompt`` and
  ``negative_prompt`` arguments;
* token cost lookup by quality tier (30 / 50 / 100);
* debit-first accounting that surfaces ``InsufficientTokensError``
  before any provider call;
* result extraction from the assorted Composio response shapes
  (``url``, ``image_url``, ``images[0].url`` …);
* failure paths: provider exception, ``successful=False`` payload,
  missing URL — each path translated to :class:`ImageProviderError`
  and logged with a zero-cost audit row.

The DB-backed flow (real ``TokenService.spend`` + ``token_usage_logs``)
is covered by ``test_image_generation_db.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from app.services.composio import (
    ComposioTransientError,
    MockComposioClient,
    ToolInvocation,
    ToolResult,
)
from app.services.image_generation import (
    DEFAULT_ASPECT_RATIO,
    MAX_NEGATIVE_PROMPT_LENGTH,
    MAX_PROMPT_LENGTH,
    QUALITY_COST,
    QUALITY_HD,
    QUALITY_STANDARD,
    QUALITY_ULTRA_HD,
    SERVICE_TYPE,
    SUPPORTED_ASPECT_RATIOS,
    ImageGenerationResult,
    ImageGenerationService,
    ImageProviderError,
    InvalidAspectRatioError,
    InvalidPromptError,
    InvalidQualityError,
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
    """Stand-in for :class:`TokenService` that doesn't touch a DB.

    Configurable per-user balances and a recorded list of ``spend``
    calls so tests can assert what the service tried to debit.
    """

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
) -> ImageGenerationService:
    service = ImageGenerationService(session, composio)  # type: ignore[arg-type]
    # Replace the internal TokenService with our stub — the constructor
    # creates a real one (which would fail without a DB).
    service._tokens = tokens  # type: ignore[assignment]
    return service


# --------------------------------------------------------------- constants


def test_quality_cost_table_matches_spec() -> None:
    assert QUALITY_COST == {
        QUALITY_STANDARD: 30,
        QUALITY_HD: 50,
        QUALITY_ULTRA_HD: 100,
    }


def test_service_type_is_image() -> None:
    assert SERVICE_TYPE == "image"


def test_default_aspect_ratio_is_supported() -> None:
    assert DEFAULT_ASPECT_RATIO in SUPPORTED_ASPECT_RATIOS


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
async def test_rejects_overlong_prompt(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    service = _build_service(fake_session, composio_mock, fake_tokens)
    with pytest.raises(InvalidPromptError):
        await service.generate(user_id=42, prompt="a" * (MAX_PROMPT_LENGTH + 1))


@pytest.mark.asyncio
async def test_rejects_overlong_negative_prompt(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    service = _build_service(fake_session, composio_mock, fake_tokens)
    with pytest.raises(InvalidPromptError):
        await service.generate(
            user_id=42,
            prompt="a cat",
            negative_prompt="x" * (MAX_NEGATIVE_PROMPT_LENGTH + 1),
        )


@pytest.mark.asyncio
async def test_rejects_unknown_quality(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    service = _build_service(fake_session, composio_mock, fake_tokens)
    with pytest.raises(InvalidQualityError):
        await service.generate(user_id=42, prompt="a cat", quality="ultra")


@pytest.mark.asyncio
async def test_rejects_unknown_aspect_ratio(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    service = _build_service(fake_session, composio_mock, fake_tokens)
    with pytest.raises(InvalidAspectRatioError):
        await service.generate(user_id=42, prompt="a cat", aspect_ratio="42:7")


@pytest.mark.asyncio
async def test_empty_aspect_ratio_falls_back_to_default(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock.set_response("image_gen", data={"url": "https://img.test/cat.png"})
    service = _build_service(fake_session, composio_mock, fake_tokens)
    outcome = await service.generate(user_id=42, prompt="a cat", aspect_ratio="")
    assert outcome.aspect_ratio == DEFAULT_ASPECT_RATIO


# ------------------------------------------------------------- happy path


@pytest.mark.asyncio
async def test_generate_debits_correct_cost_for_quality(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock.set_response("image_gen", data={"url": "https://img.test/sunset.png"})
    service = _build_service(fake_session, composio_mock, fake_tokens)

    outcome = await service.generate(user_id=42, prompt="a sunset", quality=QUALITY_HD)

    assert isinstance(outcome, ImageGenerationResult)
    assert outcome.tokens_spent == 50
    assert outcome.new_balance == 500 - 50
    assert outcome.result_url == "https://img.test/sunset.png"
    assert outcome.composio_tool == "image_gen"
    assert outcome.quality == QUALITY_HD
    assert outcome.aspect_ratio == DEFAULT_ASPECT_RATIO
    assert outcome.usage_log_id > 0
    assert outcome.transaction_id > 0


@pytest.mark.asyncio
async def test_generate_passes_request_params_to_composio(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock.set_response("image_gen", data={"url": "https://img.test/a.png"})
    service = _build_service(fake_session, composio_mock, fake_tokens)

    await service.generate(
        user_id=42,
        prompt="  a cat  ",
        quality=QUALITY_STANDARD,
        aspect_ratio="16:9",
        negative_prompt=" blurry ",
        request_id="req-1",
    )

    assert len(composio_mock.calls) == 1
    call: ToolInvocation = composio_mock.calls[0]
    assert call.tool == "image_gen"
    assert call.service_type == "image"
    assert call.request_id == "req-1"
    assert call.params == {
        "prompt": "a cat",  # trimmed
        "quality": "standard",
        "aspect_ratio": "16:9",
        "negative_prompt": "blurry",  # trimmed
    }
    assert call.metadata == {"app_user_id": "42"}


@pytest.mark.asyncio
async def test_generate_records_spend_with_audit_metadata(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock.set_response(
        "image_gen",
        data={"url": "https://img.test/a.png"},
        mcp_server="composio-prod-1",
    )
    service = _build_service(fake_session, composio_mock, fake_tokens)

    await service.generate(
        user_id=42,
        prompt="a cat",
        quality=QUALITY_STANDARD,
        aspect_ratio="1:1",
    )

    assert len(fake_tokens.spends) == 1
    spend = fake_tokens.spends[0]
    assert spend.user_id == 42
    assert spend.amount == 30
    assert spend.service == "image"
    assert spend.response_status == "ok"
    assert spend.composio_tool == "image_gen"
    assert spend.mcp_server == "composio-prod-1"
    # ``request_params`` must capture the prompt + params so admins can
    # audit "what did the user ask for" without re-fetching the request.
    assert spend.request_params is not None
    assert spend.request_params["prompt"] == "a cat"
    assert spend.request_params["quality"] == "standard"
    assert spend.request_params["aspect_ratio"] == "1:1"


@pytest.mark.asyncio
async def test_generate_costs_for_each_quality(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
) -> None:
    composio_mock.set_response("image_gen", data={"url": "https://img.test/a.png"})
    for quality, expected_cost in QUALITY_COST.items():
        tokens = _FakeTokenService(balances={1: 1_000})
        service = _build_service(fake_session, composio_mock, tokens)
        outcome = await service.generate(user_id=1, prompt="x", quality=quality)
        assert outcome.tokens_spent == expected_cost
        assert outcome.new_balance == 1_000 - expected_cost


# ---------------------------------------------------- URL extraction shapes


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"url": "https://img.test/a.png"}, "https://img.test/a.png"),
        ({"image_url": "https://img.test/b.png"}, "https://img.test/b.png"),
        ({"result_url": "https://img.test/c.png"}, "https://img.test/c.png"),
        ({"output_url": "https://img.test/d.png"}, "https://img.test/d.png"),
        ({"images": ["https://img.test/e.png"]}, "https://img.test/e.png"),
        (
            {"images": [{"url": "https://img.test/f.png"}]},
            "https://img.test/f.png",
        ),
        (
            {"images": [{"image_url": "https://img.test/g.png"}]},
            "https://img.test/g.png",
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
    composio_mock.set_response("image_gen", data=payload)
    service = _build_service(fake_session, composio_mock, fake_tokens)

    outcome = await service.generate(user_id=42, prompt="a cat")
    assert outcome.result_url == expected


# --------------------------------------------------------- balance + provider


@pytest.mark.asyncio
async def test_insufficient_balance_is_raised_before_provider_call(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
) -> None:
    tokens = _FakeTokenService(balances={42: 10})
    composio_mock.set_response("image_gen", data={"url": "https://img.test/a.png"})
    service = _build_service(fake_session, composio_mock, tokens)

    with pytest.raises(InsufficientTokensError) as exc:
        await service.generate(user_id=42, prompt="a cat", quality=QUALITY_STANDARD)
    assert exc.value.required == 30
    assert exc.value.available == 10
    # The provider must NOT have been called.
    assert composio_mock.calls == []
    # And no spend was recorded.
    assert tokens.spends == []


@pytest.mark.asyncio
async def test_unknown_user_raises_user_not_found(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
) -> None:
    tokens = _FakeTokenService(balances={})  # no users
    service = _build_service(fake_session, composio_mock, tokens)
    with pytest.raises(UserNotFoundError):
        await service.generate(user_id=999, prompt="a cat")


@pytest.mark.asyncio
async def test_provider_error_is_translated_and_logged(
    fake_session: _FakeSession,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock = MockComposioClient()
    composio_mock.set_error("image_gen", ComposioTransientError("upstream 503"))
    service = _build_service(fake_session, composio_mock, fake_tokens)

    with pytest.raises(ImageProviderError) as exc:
        await service.generate(user_id=42, prompt="a cat")
    assert "image provider call failed" in str(exc.value)
    assert exc.value.provider_error is not None
    assert len(fake_tokens.spends) == 1
    assert len(fake_tokens.refunds) == 1
    # Balance returns to its original value after the refund.
    assert fake_tokens.balances[42] == 500


@pytest.mark.asyncio
async def test_unsuccessful_provider_response_is_translated(
    fake_session: _FakeSession,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock = MockComposioClient()
    composio_mock.set_response(
        "image_gen",
        successful=False,
        data={"url": "https://img.test/a.png"},
        error="moderation_blocked",
    )
    service = _build_service(fake_session, composio_mock, fake_tokens)

    with pytest.raises(ImageProviderError) as exc:
        await service.generate(user_id=42, prompt="a cat")
    assert exc.value.provider_error == "moderation_blocked"
    assert len(fake_tokens.spends) == 1
    assert len(fake_tokens.refunds) == 1
    assert fake_tokens.balances[42] == 500


@pytest.mark.asyncio
async def test_missing_url_audits_failure_and_raises(
    fake_session: _FakeSession,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock = MockComposioClient()
    composio_mock.set_response("image_gen", data={"unexpected": "shape"})
    service = _build_service(fake_session, composio_mock, fake_tokens)

    with pytest.raises(ImageProviderError):
        await service.generate(user_id=42, prompt="a cat")

    # ``log_invocation`` writes a TokenUsageLog row directly via session.add
    # so the audit row should be present in our fake session.
    assert len(fake_session.added) >= 1
    assert fake_session.flushes >= 1
    # The debit is refunded, so the failure path has no net charge.
    assert len(fake_tokens.spends) == 1
    assert len(fake_tokens.refunds) == 1
    assert fake_tokens.balances[42] == 500


# --------------------------------------------------------- handler dispatch


@pytest.mark.asyncio
async def test_handler_overrides_response_per_invocation(
    fake_session: _FakeSession,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock = MockComposioClient()

    async def dynamic(invocation: ToolInvocation) -> ToolResult:
        return ToolResult(
            tool=invocation.tool,
            successful=True,
            data={"url": f"https://img.test/{invocation.params['prompt']}.png"},
        )

    composio_mock.set_handler("image_gen", dynamic)
    service = _build_service(fake_session, composio_mock, fake_tokens)

    outcome = await service.generate(user_id=42, prompt="rocket")
    assert outcome.result_url == "https://img.test/rocket.png"
