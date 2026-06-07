"""Unit tests for :class:`DocumentAnalysisService`.

The service is exercised against :class:`MockComposioClient` plus an
in-memory stub for the SQLAlchemy session / :class:`TokenService` so
the suite runs without a database (same pattern as
``test_image_generation.py`` / ``test_web_search.py`` /
``test_voice_processing.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from app.services.composio import (
    ComposioTransientError,
    MockComposioClient,
    ToolInvocation,
)
from app.services.document_analysis import (
    DOCUMENT_COST,
    FORMAT_DOCX,
    FORMAT_PDF,
    FORMAT_TXT,
    MAX_DOCUMENT_URL_LENGTH,
    MAX_FILE_BYTES_FREE,
    MAX_FILE_BYTES_PREMIUM,
    MAX_FILENAME_LENGTH,
    MAX_QUESTION_LENGTH,
    SERVICE_TYPE,
    SUPPORTED_FORMATS,
    DocumentAnalysisResult,
    DocumentAnalysisService,
    DocumentProviderError,
    DocumentTooLargeError,
    InvalidDocumentError,
    InvalidDocumentFormatError,
    InvalidQuestionError,
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
) -> DocumentAnalysisService:
    service = DocumentAnalysisService(session, composio)  # type: ignore[arg-type]
    service._tokens = tokens  # type: ignore[assignment]
    return service


def _ok_payload() -> dict[str, Any]:
    return {
        "text": "Lorem ipsum dolor sit amet. " * 5,
        "summary": "Latin placeholder text.",
        "page_count": 3,
    }


# --------------------------------------------------------------- constants


def test_document_cost_is_twenty() -> None:
    assert DOCUMENT_COST == 20


def test_service_type_is_document() -> None:
    assert SERVICE_TYPE == "document"


def test_supported_formats_match_aliases() -> None:
    assert frozenset({FORMAT_PDF, FORMAT_DOCX, FORMAT_TXT}) == SUPPORTED_FORMATS


def test_size_caps_are_correctly_ordered() -> None:
    assert MAX_FILE_BYTES_FREE < MAX_FILE_BYTES_PREMIUM
    assert MAX_FILE_BYTES_FREE == 10 * 1024 * 1024
    assert MAX_FILE_BYTES_PREMIUM == 50 * 1024 * 1024


# ------------------------------------------------------------- validation


@pytest.mark.asyncio
async def test_rejects_missing_document(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    service = _build_service(fake_session, composio_mock, fake_tokens)
    with pytest.raises(InvalidDocumentError):
        await service.analyze(user_id=42, format=FORMAT_PDF)
    assert composio_mock.calls == []


@pytest.mark.asyncio
async def test_rejects_overlong_document_url(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    service = _build_service(fake_session, composio_mock, fake_tokens)
    with pytest.raises(InvalidDocumentError):
        await service.analyze(
            user_id=42,
            document_url="https://example.com/" + ("a" * (MAX_DOCUMENT_URL_LENGTH + 1)) + ".pdf",
        )


@pytest.mark.asyncio
async def test_rejects_non_http_document_url(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    service = _build_service(fake_session, composio_mock, fake_tokens)
    with pytest.raises(InvalidDocumentError):
        await service.analyze(user_id=42, document_url="ftp://example.com/a.pdf")


@pytest.mark.asyncio
async def test_rejects_overlong_filename(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    service = _build_service(fake_session, composio_mock, fake_tokens)
    with pytest.raises(InvalidDocumentError):
        await service.analyze(
            user_id=42,
            document_url="https://example.com/a.pdf",
            filename="x" * (MAX_FILENAME_LENGTH + 1),
        )


@pytest.mark.asyncio
async def test_rejects_unknown_format(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    service = _build_service(fake_session, composio_mock, fake_tokens)
    with pytest.raises(InvalidDocumentFormatError):
        await service.analyze(
            user_id=42,
            document_url="https://example.com/a.xls",
        )


@pytest.mark.asyncio
async def test_rejects_missing_format_when_indeterminable(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    service = _build_service(fake_session, composio_mock, fake_tokens)
    with pytest.raises(InvalidDocumentFormatError):
        # base64 input with no filename and no explicit format — no way to tell.
        await service.analyze(user_id=42, document_base64="aGVsbG8=")


@pytest.mark.asyncio
async def test_rejects_overlong_question(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    service = _build_service(fake_session, composio_mock, fake_tokens)
    with pytest.raises(InvalidQuestionError):
        await service.analyze(
            user_id=42,
            document_url="https://example.com/a.pdf",
            question="q" * (MAX_QUESTION_LENGTH + 1),
        )


@pytest.mark.asyncio
async def test_rejects_negative_file_size(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    service = _build_service(fake_session, composio_mock, fake_tokens)
    with pytest.raises(InvalidDocumentError):
        await service.analyze(
            user_id=42,
            document_url="https://example.com/a.pdf",
            file_size_bytes=-1,
        )


# -------------------------------------------------------- size cap behaviour


@pytest.mark.asyncio
async def test_free_user_size_cap_enforced(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    service = _build_service(fake_session, composio_mock, fake_tokens)
    with pytest.raises(DocumentTooLargeError) as exc:
        await service.analyze(
            user_id=42,
            document_url="https://example.com/a.pdf",
            file_size_bytes=MAX_FILE_BYTES_FREE + 1,
            is_premium=False,
        )
    assert exc.value.size == MAX_FILE_BYTES_FREE + 1
    assert exc.value.limit == MAX_FILE_BYTES_FREE
    assert exc.value.is_premium is False
    assert composio_mock.calls == []


@pytest.mark.asyncio
async def test_premium_user_size_cap_is_higher(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    """A free-tier-busting upload should pass for premium users."""
    composio_mock.set_response("document_parser", data=_ok_payload())
    service = _build_service(fake_session, composio_mock, fake_tokens)

    # 15 MB > free 10 MB but < premium 50 MB.
    size = 15 * 1024 * 1024
    outcome = await service.analyze(
        user_id=42,
        document_url="https://example.com/a.pdf",
        file_size_bytes=size,
        is_premium=True,
    )
    assert outcome.file_size_bytes == size


@pytest.mark.asyncio
async def test_premium_user_still_capped_at_50mb(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    service = _build_service(fake_session, composio_mock, fake_tokens)
    with pytest.raises(DocumentTooLargeError) as exc:
        await service.analyze(
            user_id=42,
            document_url="https://example.com/a.pdf",
            file_size_bytes=MAX_FILE_BYTES_PREMIUM + 1,
            is_premium=True,
        )
    assert exc.value.is_premium is True
    assert exc.value.limit == MAX_FILE_BYTES_PREMIUM


@pytest.mark.asyncio
async def test_size_inferred_from_base64_when_not_provided(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock.set_response("document_parser", data=_ok_payload())
    service = _build_service(fake_session, composio_mock, fake_tokens)

    # base64 padding: every 4 chars represent up to 3 bytes.
    b64 = "QUJDREVG"  # decodes to 6 bytes; service over-approximates to 6.
    outcome = await service.analyze(
        user_id=42,
        document_base64=b64,
        format=FORMAT_TXT,
    )
    assert outcome.file_size_bytes == (len(b64) // 4) * 3


# --------------------------------------------------------- format inference


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs, expected",
    [
        ({"format": "PDF"}, FORMAT_PDF),
        ({"format": ".pdf"}, FORMAT_PDF),
        ({"format": "docx"}, FORMAT_DOCX),
        ({"format": "doc"}, FORMAT_DOCX),
        ({"format": "txt"}, FORMAT_TXT),
        ({"format": "text"}, FORMAT_TXT),
    ],
)
async def test_explicit_format_takes_priority(
    fake_session: _FakeSession,
    fake_tokens: _FakeTokenService,
    kwargs: dict[str, Any],
    expected: str,
) -> None:
    composio_mock = MockComposioClient()
    composio_mock.set_response("document_parser", data=_ok_payload())
    service = _build_service(fake_session, composio_mock, fake_tokens)

    outcome = await service.analyze(
        user_id=42,
        document_url="https://example.com/a.unknown",
        **kwargs,
    )
    assert outcome.format == expected


@pytest.mark.asyncio
async def test_format_inferred_from_filename(
    fake_session: _FakeSession,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock = MockComposioClient()
    composio_mock.set_response("document_parser", data=_ok_payload())
    service = _build_service(fake_session, composio_mock, fake_tokens)

    outcome = await service.analyze(
        user_id=42,
        document_base64="aGVsbG8=",
        filename="Report.DOCX",
    )
    assert outcome.format == FORMAT_DOCX


@pytest.mark.asyncio
async def test_format_inferred_from_url_with_query_string(
    fake_session: _FakeSession,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock = MockComposioClient()
    composio_mock.set_response("document_parser", data=_ok_payload())
    service = _build_service(fake_session, composio_mock, fake_tokens)

    outcome = await service.analyze(
        user_id=42,
        document_url="https://example.com/files/report.pdf?token=abc&v=2",
    )
    # Query string is stripped before peeking at the extension.
    assert outcome.format == FORMAT_PDF


# ------------------------------------------------------------- happy path


@pytest.mark.asyncio
async def test_analyze_debits_flat_cost(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock.set_response("document_parser", data=_ok_payload())
    service = _build_service(fake_session, composio_mock, fake_tokens)

    outcome = await service.analyze(user_id=42, document_url="https://example.com/a.pdf")

    assert isinstance(outcome, DocumentAnalysisResult)
    assert outcome.tokens_spent == DOCUMENT_COST
    assert outcome.new_balance == 500 - DOCUMENT_COST
    assert outcome.format == FORMAT_PDF
    assert outcome.text.startswith("Lorem ipsum")
    assert outcome.summary == "Latin placeholder text."
    assert outcome.page_count == 3
    assert outcome.char_count == len(outcome.text)
    assert outcome.answer is None
    assert outcome.composio_tool == "document_parser"
    assert outcome.usage_log_id > 0
    assert outcome.transaction_id > 0


@pytest.mark.asyncio
async def test_analyze_with_question_returns_answer(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    payload = dict(_ok_payload())
    payload["answer"] = "The third paragraph mentions it."
    composio_mock.set_response("document_parser", data=payload)
    service = _build_service(fake_session, composio_mock, fake_tokens)

    outcome = await service.analyze(
        user_id=42,
        document_url="https://example.com/a.pdf",
        question="Where is X mentioned?",
    )
    assert outcome.answer == "The third paragraph mentions it."
    assert outcome.question == "Where is X mentioned?"
    # Question text is fingerprinted (length only) in the audit row.
    assert fake_tokens.spends[0].request_params is not None
    assert fake_tokens.spends[0].request_params["question_len"] == len("Where is X mentioned?")


@pytest.mark.asyncio
async def test_analyze_passes_request_metadata_to_composio(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock.set_response("document_parser", data=_ok_payload())
    service = _build_service(fake_session, composio_mock, fake_tokens)

    await service.analyze(
        user_id=42,
        document_url="https://example.com/a.pdf",
        question="What is X?",
        filename="a.pdf",
        request_id="req-doc-1",
        composio_user_id="composio-user-42",
    )

    assert len(composio_mock.calls) == 1
    call: ToolInvocation = composio_mock.calls[0]
    assert call.tool == "document_parser"
    assert call.service_type == "document"
    assert call.request_id == "req-doc-1"
    assert call.user_id == "composio-user-42"
    assert call.metadata == {"app_user_id": "42"}
    assert call.params["document_url"] == "https://example.com/a.pdf"
    assert call.params["format"] == FORMAT_PDF
    assert call.params["filename"] == "a.pdf"
    assert call.params["question"] == "What is X?"


@pytest.mark.asyncio
async def test_analyze_base64_inlined_in_provider_params(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock.set_response("document_parser", data=_ok_payload())
    service = _build_service(fake_session, composio_mock, fake_tokens)

    await service.analyze(user_id=42, document_base64="aGVsbG8=", format=FORMAT_TXT)

    call = composio_mock.calls[0]
    # Full payload is sent to Composio…
    assert call.params["document_base64"] == "aGVsbG8="
    # …but only its length is recorded in the audit row.
    audit = fake_tokens.spends[0].request_params
    assert audit is not None
    assert audit["document_base64_len"] == len("aGVsbG8=")
    assert "document_base64" not in audit


@pytest.mark.asyncio
async def test_analyze_records_spend_with_audit_metadata(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock.set_response(
        "document_parser",
        data=_ok_payload(),
        mcp_server="composio-prod-1",
    )
    service = _build_service(fake_session, composio_mock, fake_tokens)

    await service.analyze(user_id=42, document_url="https://example.com/a.pdf")

    assert len(fake_tokens.spends) == 1
    spend = fake_tokens.spends[0]
    assert spend.user_id == 42
    assert spend.amount == DOCUMENT_COST
    assert spend.service == "document"
    assert spend.composio_tool == "document_parser"
    assert spend.mcp_server == "composio-prod-1"
    assert spend.request_params is not None
    assert spend.request_params["format"] == FORMAT_PDF
    assert spend.request_params["document_url"] == "https://example.com/a.pdf"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload, expected_text, expected_summary, expected_pages",
    [
        ({"text": "hi", "summary": "s", "page_count": 1}, "hi", "s", 1),
        ({"content": "hi"}, "hi", None, None),
        ({"extracted_text": "hi"}, "hi", None, None),
        ({"body": "hi"}, "hi", None, None),
        ({"full_text": "hi"}, "hi", None, None),
        ({"document": {"text": "nested"}}, "nested", None, None),
        ({"text": "hi", "abstract": "a"}, "hi", "a", None),
        ({"text": "hi", "overview": "o"}, "hi", "o", None),
        (
            {"text": "hi", "summary": {"text": "from-dict"}},
            "hi",
            "from-dict",
            None,
        ),
        ({"text": "hi", "pages": 7}, "hi", None, 7),
        ({"text": "hi", "num_pages": 9}, "hi", None, 9),
        (
            {"text": "hi", "document": {"page_count": 12}},
            "hi",
            None,
            12,
        ),
    ],
)
async def test_analyze_normalises_payload_shapes(
    fake_session: _FakeSession,
    fake_tokens: _FakeTokenService,
    payload: dict[str, Any],
    expected_text: str,
    expected_summary: str | None,
    expected_pages: int | None,
) -> None:
    composio_mock = MockComposioClient()
    composio_mock.set_response("document_parser", data=payload)
    service = _build_service(fake_session, composio_mock, fake_tokens)

    outcome = await service.analyze(user_id=42, document_url="https://example.com/a.pdf")
    assert outcome.text == expected_text
    assert outcome.summary == expected_summary
    assert outcome.page_count == expected_pages


@pytest.mark.asyncio
async def test_analyze_extracts_answer_from_nested_dict(
    fake_session: _FakeSession,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock = MockComposioClient()
    composio_mock.set_response(
        "document_parser",
        data={
            "text": "body",
            "answer": {"text": "Section 4 mentions it."},
        },
    )
    service = _build_service(fake_session, composio_mock, fake_tokens)

    outcome = await service.analyze(
        user_id=42,
        document_url="https://example.com/a.pdf",
        question="Where?",
    )
    assert outcome.answer == "Section 4 mentions it."


@pytest.mark.asyncio
async def test_summary_only_payload_is_accepted(
    fake_session: _FakeSession,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock = MockComposioClient()
    composio_mock.set_response(
        "document_parser",
        data={"summary": "Just the summary."},
    )
    service = _build_service(fake_session, composio_mock, fake_tokens)

    outcome = await service.analyze(user_id=42, document_url="https://example.com/a.pdf")
    assert outcome.summary == "Just the summary."
    # Empty text is still acceptable when summary is present.
    assert outcome.tokens_spent == DOCUMENT_COST


# --------------------------------------------------------- balance + provider


@pytest.mark.asyncio
async def test_insufficient_balance_is_raised_before_provider_call(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
) -> None:
    tokens = _FakeTokenService(balances={42: 10})  # below 20
    composio_mock.set_response("document_parser", data=_ok_payload())
    service = _build_service(fake_session, composio_mock, tokens)

    with pytest.raises(InsufficientTokensError) as exc:
        await service.analyze(user_id=42, document_url="https://example.com/a.pdf")
    assert exc.value.required == DOCUMENT_COST
    assert exc.value.available == 10
    assert composio_mock.calls == []
    assert tokens.spends == []


@pytest.mark.asyncio
async def test_unknown_user_raises_user_not_found(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
) -> None:
    tokens = _FakeTokenService(balances={})
    service = _build_service(fake_session, composio_mock, tokens)
    with pytest.raises(UserNotFoundError):
        await service.analyze(user_id=999, document_url="https://example.com/a.pdf")


@pytest.mark.asyncio
async def test_provider_error_is_translated(
    fake_session: _FakeSession,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock = MockComposioClient()
    composio_mock.set_error("document_parser", ComposioTransientError("upstream 503"))
    service = _build_service(fake_session, composio_mock, fake_tokens)

    with pytest.raises(DocumentProviderError) as exc:
        await service.analyze(user_id=42, document_url="https://example.com/a.pdf")
    assert exc.value.provider_error is not None
    assert "document provider call failed" in str(exc.value)
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
        "document_parser",
        successful=False,
        data={},
        error="parsing_failed",
    )
    service = _build_service(fake_session, composio_mock, fake_tokens)

    with pytest.raises(DocumentProviderError) as exc:
        await service.analyze(user_id=42, document_url="https://example.com/a.pdf")
    assert exc.value.provider_error == "parsing_failed"
    assert len(fake_tokens.spends) == 1
    assert len(fake_tokens.refunds) == 1
    assert fake_tokens.balances[42] == 500


@pytest.mark.asyncio
async def test_empty_response_audits_failure_and_raises(
    fake_session: _FakeSession,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock = MockComposioClient()
    composio_mock.set_response("document_parser", data={})
    service = _build_service(fake_session, composio_mock, fake_tokens)

    with pytest.raises(DocumentProviderError):
        await service.analyze(user_id=42, document_url="https://example.com/a.pdf")

    assert len(fake_session.added) >= 1
    assert fake_session.flushes >= 1
    assert len(fake_tokens.spends) == 1
    assert len(fake_tokens.refunds) == 1
    assert fake_tokens.balances[42] == 500
