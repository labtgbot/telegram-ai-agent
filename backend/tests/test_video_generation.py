"""Unit tests for :class:`VideoGenerationService`.

The service is async-by-design (provider returns a ``job_id`` and the
worker polls); the suite exercises it end-to-end against a
:class:`MockComposioClient` plus an in-memory session / token stub so it
runs without a database.

Coverage:

* tariff catalog (cost + duration) matches the issue spec;
* tariff resolution from ``tariff`` / ``duration_s`` (and conflict
  detection when both disagree);
* prompt / reference-image / style validation;
* pre-flight balance check raises *before* any provider call;
* successful submit transitions ``pending → queued / in_progress / succeeded``
  depending on provider response shape;
* synchronous-style success (provider returns URL on submit) is captured;
* submit failure refunds the up-front spend and lands as ``refunded``;
* idempotency: same ``request_id`` returns the existing row without
  double-charging;
* polling: status transitions on subsequent ``poll`` calls;
* URL extraction from the assorted shapes (``video_url`` / ``url`` /
  nested ``videos[0]`` / ``output.url`` …).
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
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
from app.services.video_generation import (
    DURATION_TO_TARIFF,
    SERVICE_TYPE,
    SUPPORTED_TARIFFS,
    TARIFF_COST,
    TARIFF_DURATION,
    TARIFF_LONG,
    TARIFF_MEDIUM,
    TARIFF_SHORT,
    InvalidPromptError,
    InvalidReferenceImageError,
    InvalidTariffError,
    VideoGenerationError,
    VideoGenerationService,
    VideoJobNotFoundError,
    VideoJobView,
    VideoProviderError,
)

# --------------------------------------------------------------- stubs


@dataclass
class _RecordedSpend:
    user_id: int
    amount: int
    service: str
    response_status: str | None
    request_params: dict[str, Any] | None


@dataclass
class _RecordedRefund:
    transaction_id: int
    reason: str | None


class _FakeTokenService:
    """Drop-in for :class:`TokenService` — no DB."""

    def __init__(self, *, balances: dict[int, int] | None = None) -> None:
        self.balances: dict[int, int] = dict(balances or {})
        self.spends: list[_RecordedSpend] = []
        self.refunds: list[_RecordedRefund] = []
        self._next_tx = 1000
        self._next_log = 5000

    async def get_balance(self, user_id: int) -> int:
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
        self.spends.append(
            _RecordedSpend(
                user_id=user_id,
                amount=amount,
                service=service,
                response_status=response_status,
                request_params=dict(request_params or {}),
            )
        )
        self._next_tx += 1
        self._next_log += 1
        return SpendResult(
            user_id=user_id,
            amount=amount,
            new_balance=self.balances[user_id],
            transaction_id=self._next_tx,
            transaction_type="spend",
            usage_log_id=self._next_log,
        )

    async def refund(
        self,
        *,
        transaction_id: int,
        reason: str | None = None,
    ) -> TokenOperationResult:
        # Locate the matching spend (tests don't care about original user) and
        # restore the tokens.  Real ``TokenService.refund`` uses the DB row.
        self.refunds.append(
            _RecordedRefund(transaction_id=transaction_id, reason=reason)
        )
        matched = next(
            (s for s in self.spends if s.user_id in self.balances),
            None,
        )
        if matched is None:
            raise RuntimeError("no matching spend to refund in fake service")
        self.balances[matched.user_id] += matched.amount
        self._next_tx += 1
        return TokenOperationResult(
            user_id=matched.user_id,
            amount=matched.amount,
            new_balance=self.balances[matched.user_id],
            transaction_id=self._next_tx,
            transaction_type="refund",
        )


class _FakeResult:
    """Approximates the SQLAlchemy ``Result`` interface for our queries."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalar_one_or_none(self) -> Any | None:
        if not self._rows:
            return None
        return self._rows[0]

    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list[Any]:
        return list(self._rows)


class _FakeSession:
    """Async session stub: add/flush/execute over an in-memory job list.

    ``execute`` is matched by inspecting the SQL text — good enough for
    the three lookups the service performs (by id, by request_id,
    by active statuses).
    """

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.flushes = 0
        self._jobs: list[Any] = []  # only VideoJob rows are kept here
        self._next_id = 1

    def add(self, obj: Any) -> None:
        from app.models.video_job import VideoJob

        if isinstance(obj, VideoJob):
            if obj.id is None:
                obj.id = self._next_id
                self._next_id += 1
            if obj.created_at is None:
                obj.created_at = datetime.now(UTC)
            if obj.updated_at is None:
                obj.updated_at = datetime.now(UTC)
            self._jobs.append(obj)
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushes += 1
        # The DB would normally fill defaults — replicate the minimum.
        for obj in self._jobs:
            if obj.updated_at is None:
                obj.updated_at = datetime.now(UTC)

    async def execute(self, stmt: Any) -> _FakeResult:
        text = str(stmt).lower()
        if "video_jobs" not in text:
            # Other selects (e.g. usage logs) — return empty.
            return _FakeResult([])
        try:
            compiled = stmt.compile(compile_kwargs={"literal_binds": True})
            sql = str(compiled).lower()
        except Exception:
            sql = text

        # Route based on the WHERE clause only — the SELECT projection also
        # contains "status", "id" and friends, which would otherwise trip
        # the heuristics below.
        where_idx = sql.find("where")
        where_clause = sql[where_idx:] if where_idx >= 0 else ""

        if "request_id" in where_clause:
            wanted_request = _extract_string_literal(where_clause, after="request_id")
            wanted_user = (
                _extract_int_literal(where_clause, after="user_id")
                if "user_id" in where_clause
                else None
            )
            for job in self._jobs:
                if job.request_id != wanted_request:
                    continue
                if wanted_user is not None and job.user_id != wanted_user:
                    continue
                return _FakeResult([job])
            return _FakeResult([])

        if "status in (" in where_clause:
            active = [
                j for j in self._jobs if j.status in ("pending", "queued", "in_progress")
            ]
            active.sort(key=lambda j: j.updated_at)
            return _FakeResult(active)

        if "video_jobs.id" in where_clause:
            wanted = _extract_int_literal(where_clause, after="video_jobs.id")
            wanted_user = (
                _extract_int_literal(where_clause, after="user_id")
                if "user_id" in where_clause
                else None
            )
            for job in self._jobs:
                if job.id != wanted:
                    continue
                if wanted_user is not None and job.user_id != wanted_user:
                    continue
                return _FakeResult([job])
            return _FakeResult([])

        return _FakeResult([])


def _extract_string_literal(sql: str, *, after: str) -> str | None:
    idx = sql.find(after)
    if idx < 0:
        return None
    sub = sql[idx:]
    # Find first single-quoted literal
    start = sub.find("'")
    if start < 0:
        return None
    end = sub.find("'", start + 1)
    if end < 0:
        return None
    return sub[start + 1 : end]


def _extract_int_literal(sql: str, *, after: str) -> int | None:
    idx = sql.find(after)
    if idx < 0:
        return None
    sub = sql[idx:]
    # Look for digits after the '='
    eq = sub.find("=")
    if eq < 0:
        return None
    digits: list[str] = []
    for ch in sub[eq + 1 :]:
        if ch.isdigit():
            digits.append(ch)
        elif digits:
            break
    if not digits:
        return None
    return int("".join(digits))


# --------------------------------------------------------------- fixtures


@pytest.fixture
def fake_tokens() -> _FakeTokenService:
    return _FakeTokenService(balances={42: 1_000})


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
) -> VideoGenerationService:
    service = VideoGenerationService(session, composio)  # type: ignore[arg-type]
    service._tokens = tokens  # type: ignore[assignment]
    return service


def _video_submit(
    *,
    status: str | None = "queued",
    job_id: str | None = "prov-123",
    url: str | None = None,
    successful: bool = True,
    error: str | None = None,
) -> Callable[[ToolInvocation], Awaitable[ToolResult]]:
    """Build a Composio handler that responds to submit + status calls."""

    async def _handler(invocation: ToolInvocation) -> ToolResult:
        action = invocation.params.get("action")
        data: dict[str, Any] = {}
        if action == "submit":
            if job_id is not None:
                data["job_id"] = job_id
            if status is not None:
                data["status"] = status
            if url is not None:
                data["url"] = url
        else:
            if status is not None:
                data["status"] = status
            if url is not None:
                data["url"] = url
        return ToolResult(
            tool=invocation.tool,
            successful=successful,
            data=data,
            error=error,
            service_type=invocation.service_type,
        )

    return _handler


# --------------------------------------------------------------- constants


def test_tariff_catalog_matches_spec() -> None:
    assert TARIFF_COST == {
        TARIFF_SHORT: 100,
        TARIFF_MEDIUM: 250,
        TARIFF_LONG: 800,
    }
    assert TARIFF_DURATION == {
        TARIFF_SHORT: 5,
        TARIFF_MEDIUM: 15,
        TARIFF_LONG: 60,
    }
    assert frozenset({TARIFF_SHORT, TARIFF_MEDIUM, TARIFF_LONG}) == SUPPORTED_TARIFFS


def test_duration_inverse_lookup() -> None:
    assert DURATION_TO_TARIFF == {5: TARIFF_SHORT, 15: TARIFF_MEDIUM, 60: TARIFF_LONG}


def test_service_type_is_video() -> None:
    assert SERVICE_TYPE == "video"


# --------------------------------------------------------------- validation


@pytest.mark.asyncio
async def test_rejects_empty_prompt(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    service = _build_service(fake_session, composio_mock, fake_tokens)
    with pytest.raises(InvalidPromptError):
        await service.create(
            user_id=42, prompt="   ", tariff=TARIFF_SHORT, request_id="r1"
        )
    assert composio_mock.calls == []
    assert fake_tokens.spends == []


@pytest.mark.asyncio
async def test_rejects_unknown_tariff(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    service = _build_service(fake_session, composio_mock, fake_tokens)
    with pytest.raises(InvalidTariffError):
        await service.create(
            user_id=42, prompt="x", tariff="huge_4k", request_id="r1"
        )


@pytest.mark.asyncio
async def test_rejects_mismatched_duration(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    service = _build_service(fake_session, composio_mock, fake_tokens)
    with pytest.raises(InvalidTariffError):
        await service.create(
            user_id=42,
            prompt="x",
            tariff=TARIFF_SHORT,
            duration_s=60,
            request_id="r1",
        )


@pytest.mark.asyncio
async def test_rejects_invalid_reference_url(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    service = _build_service(fake_session, composio_mock, fake_tokens)
    with pytest.raises(InvalidReferenceImageError):
        await service.create(
            user_id=42,
            prompt="x",
            tariff=TARIFF_SHORT,
            reference_image_url="javascript:alert(1)",
            request_id="r1",
        )


@pytest.mark.asyncio
async def test_request_id_is_required(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    service = _build_service(fake_session, composio_mock, fake_tokens)
    with pytest.raises(VideoGenerationError):
        await service.create(
            user_id=42, prompt="x", tariff=TARIFF_SHORT, request_id=""
        )


@pytest.mark.asyncio
async def test_duration_resolves_to_tariff(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock.set_handler("video_gen", _video_submit(status="queued"))
    service = _build_service(fake_session, composio_mock, fake_tokens)
    view = await service.create(
        user_id=42, prompt="a sunset", duration_s=15, request_id="r-dur"
    )
    assert view.tariff == TARIFF_MEDIUM
    assert view.duration_s == 15
    assert view.tokens_cost == TARIFF_COST[TARIFF_MEDIUM]


# --------------------------------------------------------------- balance check


@pytest.mark.asyncio
async def test_insufficient_balance_raises_before_provider_call(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
) -> None:
    tokens = _FakeTokenService(balances={42: 50})  # less than short_5s (100)
    composio_mock.set_handler("video_gen", _video_submit(status="queued"))
    service = _build_service(fake_session, composio_mock, tokens)

    with pytest.raises(InsufficientTokensError) as exc:
        await service.create(
            user_id=42, prompt="x", tariff=TARIFF_SHORT, request_id="r1"
        )
    assert exc.value.required == 100
    assert exc.value.available == 50
    # Provider must not be called.
    assert composio_mock.calls == []
    # No spend.
    assert tokens.spends == []


# --------------------------------------------------------------- happy path


@pytest.mark.asyncio
async def test_submit_creates_queued_job_and_debits_tokens(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock.set_handler(
        "video_gen",
        _video_submit(status="queued", job_id="prov-abc"),
    )
    service = _build_service(fake_session, composio_mock, fake_tokens)

    view = await service.create(
        user_id=42,
        prompt="a soaring dragon",
        tariff=TARIFF_MEDIUM,
        request_id="r-1",
    )

    assert isinstance(view, VideoJobView)
    assert view.status == "queued"
    assert view.tariff == TARIFF_MEDIUM
    assert view.duration_s == 15
    assert view.tokens_cost == 250
    assert view.provider_job_id == "prov-abc"
    assert view.composio_tool == "video_gen"
    assert view.transaction_id is not None
    assert view.usage_log_id is not None
    assert view.request_id == "r-1"

    # The Composio submit was issued exactly once with action=submit.
    assert len(composio_mock.calls) == 1
    call = composio_mock.calls[0]
    assert call.tool == "video_gen"
    assert call.service_type == "video"
    assert call.params["action"] == "submit"
    assert call.params["prompt"] == "a soaring dragon"
    assert call.params["tariff"] == TARIFF_MEDIUM
    assert call.params["duration_s"] == 15
    assert call.metadata == {"app_user_id": "42", "phase": "submit"}

    # Tokens were debited up-front.
    assert len(fake_tokens.spends) == 1
    spend = fake_tokens.spends[0]
    assert spend.amount == 250
    assert spend.service == "video"
    assert spend.response_status == "pending"
    assert fake_tokens.balances[42] == 1_000 - 250


@pytest.mark.asyncio
async def test_synchronous_provider_response_marks_succeeded(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock.set_handler(
        "video_gen",
        _video_submit(status="succeeded", url="https://vid.test/c.mp4"),
    )
    service = _build_service(fake_session, composio_mock, fake_tokens)

    view = await service.create(
        user_id=42, prompt="x", tariff=TARIFF_SHORT, request_id="r-sync"
    )
    assert view.status == "succeeded"
    assert view.result_url == "https://vid.test/c.mp4"
    assert view.completed_at is not None


@pytest.mark.asyncio
async def test_submit_failure_refunds_and_marks_refunded(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock.set_error(
        "video_gen", ComposioTransientError("upstream 503")
    )
    service = _build_service(fake_session, composio_mock, fake_tokens)

    with pytest.raises(VideoProviderError) as exc:
        await service.create(
            user_id=42, prompt="x", tariff=TARIFF_LONG, request_id="r-fail"
        )
    assert "video provider call failed" in str(exc.value)

    # The spend was issued *and then refunded* — net zero balance change.
    assert len(fake_tokens.spends) == 1
    assert fake_tokens.spends[0].amount == 800
    assert len(fake_tokens.refunds) == 1
    assert fake_tokens.balances[42] == 1_000


@pytest.mark.asyncio
async def test_unsuccessful_submit_response_refunds(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock.set_response(
        "video_gen",
        successful=False,
        data={},
        error="moderation_blocked",
    )
    service = _build_service(fake_session, composio_mock, fake_tokens)

    with pytest.raises(VideoProviderError) as exc:
        await service.create(
            user_id=42, prompt="x", tariff=TARIFF_SHORT, request_id="r-ml"
        )
    assert exc.value.provider_error == "moderation_blocked"
    assert len(fake_tokens.refunds) == 1
    assert fake_tokens.balances[42] == 1_000


# --------------------------------------------------------------- idempotency


@pytest.mark.asyncio
async def test_duplicate_request_id_returns_existing_row(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock.set_handler(
        "video_gen", _video_submit(status="queued", job_id="prov-x")
    )
    service = _build_service(fake_session, composio_mock, fake_tokens)

    first = await service.create(
        user_id=42, prompt="x", tariff=TARIFF_SHORT, request_id="dup"
    )
    second = await service.create(
        user_id=42, prompt="x", tariff=TARIFF_SHORT, request_id="dup"
    )

    assert first.id == second.id
    # Only one provider call, one debit.
    assert len(composio_mock.calls) == 1
    assert len(fake_tokens.spends) == 1


@pytest.mark.asyncio
async def test_duplicate_request_id_from_different_user_is_rejected(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
) -> None:
    tokens = _FakeTokenService(balances={42: 500, 43: 500})
    composio_mock.set_handler(
        "video_gen", _video_submit(status="queued", job_id="prov-x")
    )
    service = _build_service(fake_session, composio_mock, tokens)

    await service.create(
        user_id=42, prompt="x", tariff=TARIFF_SHORT, request_id="dup"
    )
    with pytest.raises(VideoGenerationError):
        await service.create(
            user_id=43, prompt="x", tariff=TARIFF_SHORT, request_id="dup"
        )


# --------------------------------------------------------------- polling


@pytest.mark.asyncio
async def test_poll_transitions_queued_to_succeeded(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    # Submit returns "queued"; subsequent status returns "succeeded".
    state = {"phase": "submit"}

    async def handler(invocation: ToolInvocation) -> ToolResult:
        action = invocation.params.get("action")
        if action == "submit":
            state["phase"] = "polled"
            return ToolResult(
                tool=invocation.tool,
                successful=True,
                data={"job_id": "prov-poll", "status": "queued"},
            )
        return ToolResult(
            tool=invocation.tool,
            successful=True,
            data={
                "status": "succeeded",
                "video_url": "https://vid.test/poll.mp4",
            },
        )

    composio_mock.set_handler("video_gen", handler)
    service = _build_service(fake_session, composio_mock, fake_tokens)

    created = await service.create(
        user_id=42, prompt="x", tariff=TARIFF_SHORT, request_id="r-poll"
    )
    assert created.status == "queued"

    refreshed = await service.poll(created.id)
    assert refreshed.status == "succeeded"
    assert refreshed.result_url == "https://vid.test/poll.mp4"


@pytest.mark.asyncio
async def test_poll_failure_refunds(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    async def handler(invocation: ToolInvocation) -> ToolResult:
        action = invocation.params.get("action")
        if action == "submit":
            return ToolResult(
                tool=invocation.tool,
                successful=True,
                data={"job_id": "prov-fail", "status": "queued"},
            )
        return ToolResult(
            tool=invocation.tool,
            successful=True,
            data={"status": "failed", "error": "content policy"},
            error="content policy",
        )

    composio_mock.set_handler("video_gen", handler)
    service = _build_service(fake_session, composio_mock, fake_tokens)

    created = await service.create(
        user_id=42, prompt="x", tariff=TARIFF_MEDIUM, request_id="r-fpoll"
    )
    assert created.status == "queued"

    refreshed = await service.poll(created.id)
    assert refreshed.status == "refunded"
    assert fake_tokens.balances[42] == 1_000  # refunded


@pytest.mark.asyncio
async def test_poll_skips_terminal_jobs(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock.set_handler(
        "video_gen",
        _video_submit(status="succeeded", url="https://vid.test/done.mp4"),
    )
    service = _build_service(fake_session, composio_mock, fake_tokens)

    created = await service.create(
        user_id=42, prompt="x", tariff=TARIFF_SHORT, request_id="r-term"
    )
    assert created.status == "succeeded"

    composio_mock.calls.clear()
    refreshed = await service.poll(created.id)
    assert refreshed.status == "succeeded"
    # No additional provider call once terminal.
    assert composio_mock.calls == []


@pytest.mark.asyncio
async def test_get_unknown_job_raises(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    service = _build_service(fake_session, composio_mock, fake_tokens)
    with pytest.raises(VideoJobNotFoundError):
        await service.get(99_999)


# ------------------------------------------------------------- URL extraction


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"video_url": "https://vid.test/a.mp4"}, "https://vid.test/a.mp4"),
        ({"url": "https://vid.test/b.mp4"}, "https://vid.test/b.mp4"),
        ({"result_url": "https://vid.test/c.mp4"}, "https://vid.test/c.mp4"),
        ({"output_url": "https://vid.test/d.mp4"}, "https://vid.test/d.mp4"),
        ({"videos": ["https://vid.test/e.mp4"]}, "https://vid.test/e.mp4"),
        (
            {"videos": [{"url": "https://vid.test/f.mp4"}]},
            "https://vid.test/f.mp4",
        ),
        (
            {"output": {"video_url": "https://vid.test/g.mp4"}},
            "https://vid.test/g.mp4",
        ),
    ],
)
async def test_extract_url_handles_response_shapes(
    fake_session: _FakeSession,
    fake_tokens: _FakeTokenService,
    payload: dict[str, Any],
    expected: str,
) -> None:
    composio = MockComposioClient()

    async def handler(invocation: ToolInvocation) -> ToolResult:
        data = {"status": "succeeded", **payload}
        if invocation.params.get("action") == "submit":
            data["job_id"] = "prov-shape"
        return ToolResult(tool=invocation.tool, successful=True, data=data)

    composio.set_handler("video_gen", handler)
    service = _build_service(fake_session, composio, fake_tokens)

    view = await service.create(
        user_id=42, prompt="x", tariff=TARIFF_SHORT, request_id=f"r-{expected}"
    )
    assert view.result_url == expected
    assert view.status == "succeeded"


# ---------------------------------------------------------- list_active


@pytest.mark.asyncio
async def test_list_active_returns_only_non_terminal(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock.set_handler(
        "video_gen", _video_submit(status="queued", job_id="p1")
    )
    service = _build_service(fake_session, composio_mock, fake_tokens)
    await service.create(
        user_id=42, prompt="a", tariff=TARIFF_SHORT, request_id="r-a"
    )

    # Mark a terminal job manually.
    composio_mock.set_handler(
        "video_gen",
        _video_submit(status="succeeded", url="https://vid.test/done.mp4"),
    )
    await service.create(
        user_id=42, prompt="b", tariff=TARIFF_SHORT, request_id="r-b"
    )

    active = await service.list_active(limit=10)
    statuses = {v.status for v in active}
    assert statuses == {"queued"}
