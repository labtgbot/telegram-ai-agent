"""Document-analysis domain service.

Phase-2 sibling of :mod:`app.services.image_generation`,
:mod:`app.services.text_generation`, :mod:`app.services.web_search` and
:mod:`app.services.voice_processing`.  The same Composio toolkit gateway,
``TokenService`` debit pattern and ``token_usage_logs`` audit shape are
reused — only the request/response payloads differ.

A single ``analyze`` call orchestrates one document-analysis round-trip:

1.  Validate the document reference (URL or base64), file format
    (PDF/DOCX/TXT), file size against the user-tier cap and the
    optional question.
2.  Pre-check the user's balance against the flat 20-token price.
3.  Invoke the Composio ``document_parser`` toolkit.
4.  Normalise the heterogenous payload into extracted text + summary
    and, when a question was asked, an answer.
5.  Atomically debit the cost via :class:`TokenService.spend` and record
    a structured row in ``token_usage_logs``.

The service flushes its writes but does **not** commit — the caller
controls the outer transaction, matching every other service in
``app.services``.

Per issue #16 the upload cap is **10 MB for free users** and
**50 MB for premium users**.  The caps live in
:data:`MAX_FILE_BYTES_FREE` / :data:`MAX_FILE_BYTES_PREMIUM` so the API
layer can render a clear error message when a free user hits the limit.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.services.composio import (
    ComposioClient,
    ComposioError,
    ToolResult,
    log_invocation,
)
from app.services.balance_cache import get_default_balance_cache
from app.services.token_service import (
    InsufficientTokensError,
    TokenService,
    UserNotFoundError,
)

logger = get_logger(__name__)


# ----------------------------------------------------------------- constants

SERVICE_TYPE: Final[str] = "document"

# Flat 20-token price — issue #16.
DOCUMENT_COST: Final[int] = 20

FORMAT_PDF: Final[str] = "pdf"
FORMAT_DOCX: Final[str] = "docx"
FORMAT_TXT: Final[str] = "txt"
SUPPORTED_FORMATS: Final[frozenset[str]] = frozenset(
    {FORMAT_PDF, FORMAT_DOCX, FORMAT_TXT}
)

# Mapping from common file extensions to the canonical format. We accept
# upper-case + leading dot variants so the API layer can pass raw input.
_FORMAT_ALIASES: Final[dict[str, str]] = {
    "pdf": FORMAT_PDF,
    "docx": FORMAT_DOCX,
    "doc": FORMAT_DOCX,
    "txt": FORMAT_TXT,
    "text": FORMAT_TXT,
}

# Size caps in bytes — see issue #16 acceptance criteria.
MAX_FILE_BYTES_FREE: Final[int] = 10 * 1024 * 1024  # 10 MB
MAX_FILE_BYTES_PREMIUM: Final[int] = 50 * 1024 * 1024  # 50 MB

MAX_QUESTION_LENGTH: Final[int] = 2000
MAX_DOCUMENT_URL_LENGTH: Final[int] = 2048
MAX_FILENAME_LENGTH: Final[int] = 255


# ----------------------------------------------------------------- errors


class DocumentAnalysisError(Exception):
    """Base class for document-analysis errors."""


class InvalidDocumentError(DocumentAnalysisError):
    """Raised when the document reference is missing, malformed, or oversized."""


class InvalidDocumentFormatError(DocumentAnalysisError):
    """Raised when the file extension is not in :data:`SUPPORTED_FORMATS`."""


class DocumentTooLargeError(DocumentAnalysisError):
    """Raised when the document size exceeds the per-tier cap.

    Exposes ``limit`` and ``size`` so the API layer can surface a clear
    "upgrade to premium for 50 MB" hint when a free user hits the cap.
    """

    def __init__(self, *, size: int, limit: int, is_premium: bool) -> None:
        super().__init__(
            f"document is {size} bytes; max for "
            f"{'premium' if is_premium else 'free'} tier is {limit}"
        )
        self.size = size
        self.limit = limit
        self.is_premium = is_premium


class InvalidQuestionError(DocumentAnalysisError):
    """Raised when the optional question is empty or too long."""


class DocumentProviderError(DocumentAnalysisError):
    """Raised when the Composio document toolkit fails.

    Exposes ``provider_error`` so the API / bot layer can include the
    upstream message in its response without re-reading the raw payload.
    """

    def __init__(self, message: str, *, provider_error: str | None = None) -> None:
        super().__init__(message)
        self.provider_error = provider_error


# --------------------------------------------------------------- result types


@dataclass(frozen=True)
class DocumentAnalysisResult:
    """Outcome of a successful ``analyze`` call.

    ``answer`` is populated only when the caller passed a ``question``.
    ``text`` is the full extracted body — callers that only want the
    summary can ignore it.
    """

    user_id: int
    format: str
    text: str
    summary: str | None = None
    answer: str | None = None
    question: str | None = None
    page_count: int | None = None
    char_count: int = 0
    file_size_bytes: int | None = None
    tokens_spent: int = 0
    new_balance: int = 0
    composio_tool: str = ""
    mcp_server: str | None = None
    processing_time_ms: int | None = None
    usage_log_id: int = 0
    transaction_id: int = 0
    request_id: str | None = None


# ------------------------------------------------------------------ service


class DocumentAnalysisService:
    """Service object — instantiate per request with the active session."""

    def __init__(
        self,
        session: AsyncSession,
        composio: ComposioClient,
    ) -> None:
        self.session = session
        self.composio = composio
        self._tokens = TokenService(session, get_default_balance_cache())

    async def analyze(
        self,
        *,
        user_id: int,
        document_url: str | None = None,
        document_base64: str | None = None,
        format: str | None = None,
        filename: str | None = None,
        file_size_bytes: int | None = None,
        question: str | None = None,
        is_premium: bool = False,
        request_id: str | None = None,
        composio_user_id: str | None = None,
    ) -> DocumentAnalysisResult:
        """Run one document analysis and debit the per-call token cost.

        Either ``document_url`` or ``document_base64`` must be provided.
        The format is taken from the explicit ``format`` argument when
        present, otherwise inferred from ``filename`` or — as a last
        resort — from the trailing extension of ``document_url``.

        Raises:
            InvalidDocumentError: missing document reference / invalid URL.
            InvalidDocumentFormatError: format outside :data:`SUPPORTED_FORMATS`.
            DocumentTooLargeError: payload over the per-tier size cap.
            InvalidQuestionError: ``question`` empty / too long.
            InsufficientTokensError: balance below :data:`DOCUMENT_COST`.
            UserNotFoundError: ``user_id`` does not exist.
            DocumentProviderError: upstream Composio failure.
        """
        url_clean, b64_clean = self._validate_reference(
            document_url=document_url,
            document_base64=document_base64,
        )
        filename_clean = self._validate_filename(filename)
        format_clean = self._resolve_format(
            format=format,
            filename=filename_clean,
            document_url=url_clean,
        )
        size_bytes = self._compute_size(
            file_size_bytes=file_size_bytes, document_base64=b64_clean
        )
        self._assert_size_within_cap(size_bytes, is_premium=is_premium)
        question_clean = self._validate_question(question)

        await self._assert_balance_sufficient(user_id, DOCUMENT_COST)

        request_params: dict[str, Any] = {
            "format": format_clean,
        }
        if url_clean is not None:
            request_params["document_url"] = url_clean
        if b64_clean is not None:
            # We only log a fingerprint of the base64 blob — storing the
            # whole payload in ``token_usage_logs`` would balloon the row.
            request_params["document_base64_len"] = len(b64_clean)
        if filename_clean is not None:
            request_params["filename"] = filename_clean
        if size_bytes is not None:
            request_params["file_size_bytes"] = size_bytes
        if question_clean is not None:
            request_params["question_len"] = len(question_clean)

        provider_params: dict[str, Any] = {
            "format": format_clean,
        }
        if url_clean is not None:
            provider_params["document_url"] = url_clean
        if b64_clean is not None:
            provider_params["document_base64"] = b64_clean
        if filename_clean is not None:
            provider_params["filename"] = filename_clean
        if question_clean is not None:
            provider_params["question"] = question_clean

        result = await self._invoke_provider(
            user_id=user_id,
            params=provider_params,
            request_id=request_id,
            composio_user_id=composio_user_id,
        )

        text = self._extract_text(result)
        summary = self._extract_summary(result)
        answer = self._extract_answer(result) if question_clean else None
        page_count = self._extract_page_count(result)

        if not text and not summary and not answer:
            await log_invocation(
                self.session,
                user_id=user_id,
                result=result,
                tokens_consumed=0,
                request_params=request_params,
            )
            raise DocumentProviderError(
                "document provider did not return any content",
                provider_error=result.error,
            )

        spend = await self._tokens.spend(
            user_id=user_id,
            amount=DOCUMENT_COST,
            service=SERVICE_TYPE,
            request_params=request_params,
            response_status="ok",
            processing_time_ms=result.latency_ms,
            composio_tool=result.tool,
            mcp_server=result.mcp_server,
        )

        logger.info(
            "document.analyzed",
            user_id=user_id,
            format=format_clean,
            file_size_bytes=size_bytes,
            char_count=len(text),
            page_count=page_count,
            has_question=question_clean is not None,
            tokens_spent=DOCUMENT_COST,
            new_balance=spend.new_balance,
            composio_tool=result.tool,
            mcp_server=result.mcp_server,
            latency_ms=result.latency_ms,
            usage_log_id=spend.usage_log_id,
            transaction_id=spend.transaction_id,
            request_id=request_id,
        )

        return DocumentAnalysisResult(
            user_id=user_id,
            format=format_clean,
            text=text,
            summary=summary,
            answer=answer,
            question=question_clean,
            page_count=page_count,
            char_count=len(text),
            file_size_bytes=size_bytes,
            tokens_spent=DOCUMENT_COST,
            new_balance=spend.new_balance,
            composio_tool=result.tool,
            mcp_server=result.mcp_server,
            processing_time_ms=result.latency_ms,
            usage_log_id=spend.usage_log_id,
            transaction_id=spend.transaction_id,
            request_id=request_id,
        )

    # -------------------------------------------------------------- internal

    async def _assert_balance_sufficient(self, user_id: int, cost: int) -> None:
        try:
            balance = await self._tokens.get_balance(user_id)
        except UserNotFoundError:
            raise
        if balance < cost:
            raise InsufficientTokensError(required=cost, available=balance)

    async def _invoke_provider(
        self,
        *,
        user_id: int,
        params: dict[str, Any],
        request_id: str | None,
        composio_user_id: str | None,
    ) -> ToolResult:
        try:
            result = await self.composio.invoke_for_service(
                SERVICE_TYPE,
                params,
                user_id=composio_user_id,
                request_id=request_id,
                metadata={"app_user_id": str(user_id)},
            )
        except ComposioError as exc:
            logger.warning(
                "document.composio_failed",
                user_id=user_id,
                error=str(exc),
                request_id=request_id,
            )
            raise DocumentProviderError(
                "document provider call failed",
                provider_error=str(exc),
            ) from exc

        if not result.successful:
            logger.warning(
                "document.composio_unsuccessful",
                user_id=user_id,
                tool=result.tool,
                error=result.error,
                request_id=request_id,
            )
            raise DocumentProviderError(
                f"document provider returned unsuccessful: "
                f"{result.error or 'unknown'}",
                provider_error=result.error,
            )
        return result

    @staticmethod
    def _extract_text(result: ToolResult) -> str:
        """Pull the extracted body from a Composio response."""
        data = result.data or {}
        for key in ("text", "content", "extracted_text", "body", "full_text"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        nested = data.get("document")
        if isinstance(nested, dict):
            for key in ("text", "content", "extracted_text"):
                value = nested.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return ""

    @staticmethod
    def _extract_summary(result: ToolResult) -> str | None:
        data = result.data or {}
        for key in ("summary", "abstract", "overview"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, dict):
                inner = value.get("text") or value.get("content")
                if isinstance(inner, str) and inner.strip():
                    return inner.strip()
        return None

    @staticmethod
    def _extract_answer(result: ToolResult) -> str | None:
        data = result.data or {}
        for key in ("answer", "response", "qa_answer"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, dict):
                inner = value.get("text") or value.get("content")
                if isinstance(inner, str) and inner.strip():
                    return inner.strip()
        return None

    @staticmethod
    def _extract_page_count(result: ToolResult) -> int | None:
        data = result.data or {}
        for key in ("page_count", "pages", "num_pages"):
            value = data.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                return value
        nested = data.get("document")
        if isinstance(nested, dict):
            for key in ("page_count", "pages", "num_pages"):
                value = nested.get(key)
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    return value
        return None

    # --------------------------------------------------------------- validators

    @staticmethod
    def _validate_reference(
        *, document_url: str | None, document_base64: str | None
    ) -> tuple[str | None, str | None]:
        url_clean: str | None = None
        b64_clean: str | None = None
        if document_url is not None:
            url_clean = str(document_url).strip() or None
        if document_base64 is not None:
            b64_clean = str(document_base64).strip() or None
        if url_clean is None and b64_clean is None:
            raise InvalidDocumentError(
                "document_url or document_base64 is required"
            )
        if url_clean is not None and len(url_clean) > MAX_DOCUMENT_URL_LENGTH:
            raise InvalidDocumentError(
                f"document_url must be at most {MAX_DOCUMENT_URL_LENGTH} characters"
            )
        if url_clean is not None and not (
            url_clean.lower().startswith("http://")
            or url_clean.lower().startswith("https://")
        ):
            raise InvalidDocumentError(
                "document_url must be an absolute http(s) URL"
            )
        return url_clean, b64_clean

    @staticmethod
    def _validate_filename(value: str | None) -> str | None:
        if value is None:
            return None
        clean = str(value).strip()
        if not clean:
            return None
        if len(clean) > MAX_FILENAME_LENGTH:
            raise InvalidDocumentError(
                f"filename must be at most {MAX_FILENAME_LENGTH} characters"
            )
        return clean

    @staticmethod
    def _resolve_format(
        *,
        format: str | None,
        filename: str | None,
        document_url: str | None,
    ) -> str:
        """Pick the canonical format key from explicit input or extension."""
        candidate: str | None = None
        if format is not None and str(format).strip():
            candidate = str(format).strip().lower().lstrip(".")
        elif filename:
            candidate = _extract_extension(filename)
        elif document_url:
            # Strip query string before peeking at the extension so
            # ``…/file.pdf?token=…`` still resolves to ``pdf``.
            without_query = document_url.split("?", 1)[0]
            candidate = _extract_extension(without_query)

        if candidate is None:
            raise InvalidDocumentFormatError(
                "format is required (or filename/URL must carry an extension)"
            )
        normalised = _FORMAT_ALIASES.get(candidate)
        if normalised is None:
            raise InvalidDocumentFormatError(
                f"unsupported format {candidate!r}; "
                f"supported: {sorted(SUPPORTED_FORMATS)}"
            )
        return normalised

    @staticmethod
    def _compute_size(
        *, file_size_bytes: int | None, document_base64: str | None
    ) -> int | None:
        if file_size_bytes is not None:
            try:
                num = int(file_size_bytes)
            except (TypeError, ValueError) as exc:
                raise InvalidDocumentError(
                    "file_size_bytes must be an integer"
                ) from exc
            if num < 0:
                raise InvalidDocumentError("file_size_bytes must be non-negative")
            return num
        if document_base64 is not None:
            # Each 4 base64 chars encode 3 bytes — over-approximate so the
            # cap rejects payloads that would decode larger than the limit.
            return (len(document_base64) // 4) * 3
        return None

    @staticmethod
    def _assert_size_within_cap(size: int | None, *, is_premium: bool) -> None:
        if size is None:
            return
        limit = MAX_FILE_BYTES_PREMIUM if is_premium else MAX_FILE_BYTES_FREE
        if size > limit:
            raise DocumentTooLargeError(
                size=size, limit=limit, is_premium=is_premium
            )

    @staticmethod
    def _validate_question(value: str | None) -> str | None:
        if value is None:
            return None
        clean = str(value).strip()
        if not clean:
            return None
        if len(clean) > MAX_QUESTION_LENGTH:
            raise InvalidQuestionError(
                f"question must be at most {MAX_QUESTION_LENGTH} characters"
            )
        return clean


# --------------------------------------------------------------- module helpers


def _extract_extension(value: str) -> str | None:
    """Return the lower-case extension (no leading dot) or ``None``."""
    if not value:
        return None
    _, dot, ext = value.rpartition(".")
    if not dot or not ext or "/" in ext or "\\" in ext:
        return None
    return ext.strip().lower() or None


__all__ = [
    "DOCUMENT_COST",
    "DocumentAnalysisError",
    "DocumentAnalysisResult",
    "DocumentAnalysisService",
    "DocumentProviderError",
    "DocumentTooLargeError",
    "FORMAT_DOCX",
    "FORMAT_PDF",
    "FORMAT_TXT",
    "InvalidDocumentError",
    "InvalidDocumentFormatError",
    "InvalidQuestionError",
    "MAX_DOCUMENT_URL_LENGTH",
    "MAX_FILE_BYTES_FREE",
    "MAX_FILE_BYTES_PREMIUM",
    "MAX_FILENAME_LENGTH",
    "MAX_QUESTION_LENGTH",
    "SERVICE_TYPE",
    "SUPPORTED_FORMATS",
]
