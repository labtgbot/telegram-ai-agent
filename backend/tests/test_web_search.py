"""Unit tests for :class:`WebSearchService`.

The service is exercised against :class:`MockComposioClient` plus an
in-memory stub for the SQLAlchemy session / :class:`TokenService` so
the suite runs without a database (same pattern as
``test_image_generation.py`` / ``test_video_generation.py``).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from app.services.composio import (
    ComposioTransientError,
    MockComposioClient,
    ToolInvocation,
    ToolResult,
)
from app.services.token_service import (
    InsufficientTokensError,
    SpendResult,
    TokenOperationResult,
    UserNotFoundError,
)
from app.services.web_search import (
    DEFAULT_MAX_RESULTS,
    MAX_MAX_RESULTS,
    MAX_QUERY_LENGTH,
    MIN_MAX_RESULTS,
    SEARCH_COST,
    SERVICE_TYPE,
    InvalidMaxResultsError,
    InvalidQueryError,
    SearchProviderError,
    WebSearchResult,
    WebSearchService,
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


class _ContendedTokenService(_FakeTokenService):
    """Fake that makes the old unlocked pre-check race deterministic."""

    def __init__(
        self,
        *,
        balances: dict[int, int] | None = None,
        expected_balance_reads: int = 2,
    ) -> None:
        super().__init__(balances=balances)
        self._spend_lock = asyncio.Lock()
        self._expected_balance_reads = expected_balance_reads
        self._balance_reads = 0
        self._all_balance_reads = asyncio.Event()

    async def get_balance(self, user_id: int) -> int:
        self.balance_calls.append(user_id)
        if user_id not in self.balances:
            raise UserNotFoundError(f"user {user_id} not found")
        self._balance_reads += 1
        if self._balance_reads >= self._expected_balance_reads:
            self._all_balance_reads.set()
        await self._all_balance_reads.wait()
        return self.balances[user_id]

    async def spend(self, **kwargs: Any) -> SpendResult:
        async with self._spend_lock:
            return await super().spend(**kwargs)


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
) -> WebSearchService:
    service = WebSearchService(session, composio)  # type: ignore[arg-type]
    service._tokens = tokens  # type: ignore[assignment]
    return service


def _ok_payload() -> dict[str, Any]:
    return {
        "results": [
            {
                "title": "Example",
                "url": "https://example.com/1",
                "snippet": "first hit",
                "source": "example.com",
            },
            {
                "title": "Second",
                "url": "https://example.com/2",
                "snippet": "second hit",
            },
        ],
        "summary": "A short summary of the search.",
    }


# --------------------------------------------------------------- constants


def test_search_cost_is_three() -> None:
    assert SEARCH_COST == 3


def test_service_type_is_search() -> None:
    assert SERVICE_TYPE == "search"


def test_default_max_results_within_range() -> None:
    assert MIN_MAX_RESULTS <= DEFAULT_MAX_RESULTS <= MAX_MAX_RESULTS


# ------------------------------------------------------------- validation


@pytest.mark.asyncio
async def test_rejects_empty_query(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    service = _build_service(fake_session, composio_mock, fake_tokens)
    with pytest.raises(InvalidQueryError):
        await service.search(user_id=42, query="   ")
    assert composio_mock.calls == []


@pytest.mark.asyncio
async def test_rejects_overlong_query(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    service = _build_service(fake_session, composio_mock, fake_tokens)
    with pytest.raises(InvalidQueryError):
        await service.search(user_id=42, query="a" * (MAX_QUERY_LENGTH + 1))


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [0, -1, MAX_MAX_RESULTS + 1, "abc"])
async def test_rejects_invalid_max_results(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
    value: Any,
) -> None:
    service = _build_service(fake_session, composio_mock, fake_tokens)
    with pytest.raises(InvalidMaxResultsError):
        await service.search(user_id=42, query="cats", max_results=value)


# ------------------------------------------------------------- happy path


@pytest.mark.asyncio
async def test_search_debits_flat_cost(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock.set_response("composio_search", data=_ok_payload())
    service = _build_service(fake_session, composio_mock, fake_tokens)

    outcome = await service.search(user_id=42, query="best cat breeds")

    assert isinstance(outcome, WebSearchResult)
    assert outcome.tokens_spent == SEARCH_COST
    assert outcome.new_balance == 500 - SEARCH_COST
    assert len(outcome.results) == 2
    assert outcome.results[0].title == "Example"
    assert outcome.results[0].url == "https://example.com/1"
    assert outcome.summary == "A short summary of the search."
    assert outcome.composio_tool == "composio_search"
    assert outcome.usage_log_id > 0
    assert outcome.transaction_id > 0


@pytest.mark.asyncio
async def test_search_respects_max_results_clip(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock.set_response("composio_search", data=_ok_payload())
    service = _build_service(fake_session, composio_mock, fake_tokens)

    outcome = await service.search(user_id=42, query="cats", max_results=1)

    assert len(outcome.results) == 1


@pytest.mark.asyncio
async def test_search_passes_request_params_to_composio(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock.set_response("composio_search", data=_ok_payload())
    service = _build_service(fake_session, composio_mock, fake_tokens)

    await service.search(
        user_id=42,
        query=" cats ",
        max_results=7,
        request_id="req-1",
    )

    assert len(composio_mock.calls) == 1
    call: ToolInvocation = composio_mock.calls[0]
    assert call.tool == "composio_search"
    assert call.service_type == "search"
    assert call.request_id == "req-1"
    assert call.params == {"query": "cats", "max_results": 7}
    assert call.metadata == {"app_user_id": "42"}


@pytest.mark.asyncio
async def test_search_records_spend_with_audit_metadata(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock.set_response("composio_search", data=_ok_payload(), mcp_server="composio-prod-1")
    service = _build_service(fake_session, composio_mock, fake_tokens)

    await service.search(user_id=42, query="cats")

    assert len(fake_tokens.spends) == 1
    spend = fake_tokens.spends[0]
    assert spend.user_id == 42
    assert spend.amount == SEARCH_COST
    assert spend.service == "search"
    assert spend.composio_tool == "composio_search"
    assert spend.mcp_server == "composio-prod-1"
    assert spend.request_params is not None
    assert spend.request_params["query"] == "cats"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data, expected_count",
    [
        ({"items": [{"title": "T", "url": "https://t/"}]}, 1),
        ({"organic": [{"title": "O", "url": "https://o/"}]}, 1),
        (
            {"organic_results": [{"title": "OR", "url": "https://or/"}]},
            1,
        ),
        ({"search_results": [{"title": "S", "url": "https://s/"}]}, 1),
        ({"results": ["https://bare-string/"]}, 1),
    ],
)
async def test_search_normalises_various_payload_shapes(
    fake_session: _FakeSession,
    fake_tokens: _FakeTokenService,
    data: dict[str, Any],
    expected_count: int,
) -> None:
    composio_mock = MockComposioClient()
    composio_mock.set_response("composio_search", data=data)
    service = _build_service(fake_session, composio_mock, fake_tokens)

    outcome = await service.search(user_id=42, query="x")
    assert len(outcome.results) == expected_count


@pytest.mark.asyncio
async def test_search_picks_summary_when_only_summary_returned(
    fake_session: _FakeSession,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock = MockComposioClient()
    composio_mock.set_response(
        "composio_search",
        data={"results": [], "answer": "The capital is Paris."},
    )
    service = _build_service(fake_session, composio_mock, fake_tokens)

    outcome = await service.search(user_id=42, query="capital of france")
    assert outcome.summary == "The capital is Paris."
    # Even when results are empty, the summary alone is enough to debit.
    assert outcome.tokens_spent == SEARCH_COST


# --------------------------------------------------------- balance + provider


@pytest.mark.asyncio
async def test_insufficient_balance_is_raised_before_provider_call(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
) -> None:
    tokens = _FakeTokenService(balances={42: 2})  # below 3
    composio_mock.set_response("composio_search", data=_ok_payload())
    service = _build_service(fake_session, composio_mock, tokens)

    with pytest.raises(InsufficientTokensError) as exc:
        await service.search(user_id=42, query="cats")
    assert exc.value.required == SEARCH_COST
    assert exc.value.available == 2
    assert composio_mock.calls == []
    assert tokens.spends == []


@pytest.mark.asyncio
async def test_concurrent_surplus_requests_do_not_call_provider(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
) -> None:
    tokens = _ContendedTokenService(balances={42: SEARCH_COST})

    async def _slow_success(invocation: ToolInvocation) -> ToolResult:
        await asyncio.sleep(0)
        return ToolResult(
            tool=invocation.tool,
            successful=True,
            data=_ok_payload(),
            service_type=invocation.service_type,
        )

    composio_mock.set_handler("composio_search", _slow_success)
    service = _build_service(fake_session, composio_mock, tokens)

    outcomes = await asyncio.gather(
        service.search(user_id=42, query="cats"),
        service.search(user_id=42, query="dogs"),
        return_exceptions=True,
    )

    successes = [item for item in outcomes if isinstance(item, WebSearchResult)]
    insufficient = [item for item in outcomes if isinstance(item, InsufficientTokensError)]
    assert len(successes) == 1
    assert len(insufficient) == 1
    assert len(composio_mock.calls) == 1
    assert len(tokens.spends) == 1
    assert tokens.refunds == []
    assert tokens.balances[42] == 0


@pytest.mark.asyncio
async def test_unknown_user_raises_user_not_found(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
) -> None:
    tokens = _FakeTokenService(balances={})
    service = _build_service(fake_session, composio_mock, tokens)
    with pytest.raises(UserNotFoundError):
        await service.search(user_id=999, query="cats")


@pytest.mark.asyncio
async def test_provider_error_is_translated_and_logged(
    fake_session: _FakeSession,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock = MockComposioClient()
    composio_mock.set_error("composio_search", ComposioTransientError("upstream 503"))
    service = _build_service(fake_session, composio_mock, fake_tokens)

    with pytest.raises(SearchProviderError) as exc:
        await service.search(user_id=42, query="cats")
    assert "search provider call failed" in str(exc.value)
    assert exc.value.provider_error is not None
    assert len(fake_tokens.spends) == 1
    assert len(fake_tokens.refunds) == 1
    assert fake_tokens.balances[42] == 500


@pytest.mark.asyncio
async def test_unsuccessful_response_translates_to_provider_error(
    fake_session: _FakeSession,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock = MockComposioClient()
    composio_mock.set_response(
        "composio_search",
        successful=False,
        data={"results": []},
        error="rate_limited",
    )
    service = _build_service(fake_session, composio_mock, fake_tokens)

    with pytest.raises(SearchProviderError) as exc:
        await service.search(user_id=42, query="cats")
    assert exc.value.provider_error == "rate_limited"
    assert len(fake_tokens.spends) == 1
    assert len(fake_tokens.refunds) == 1
    assert fake_tokens.balances[42] == 500


@pytest.mark.asyncio
async def test_empty_response_audits_failure_and_raises(
    fake_session: _FakeSession,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock = MockComposioClient()
    composio_mock.set_response("composio_search", data={"results": []})
    service = _build_service(fake_session, composio_mock, fake_tokens)

    with pytest.raises(SearchProviderError):
        await service.search(user_id=42, query="cats")

    assert len(fake_session.added) >= 1
    assert fake_session.flushes >= 1
    assert len(fake_tokens.spends) == 1
    assert len(fake_tokens.refunds) == 1
    assert fake_tokens.balances[42] == 500
