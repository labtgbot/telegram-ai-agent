"""Web-search domain service.

Phase-2 sibling of :mod:`app.services.image_generation` and
:mod:`app.services.text_generation`.  The same Composio toolkit gateway,
``TokenService`` debit pattern and ``token_usage_logs`` audit shape are
reused — only the request/response payloads differ.

The service orchestrates one end-to-end ``search`` call:

1.  Validate the query (length, non-empty) and ``max_results``.
2.  Atomically debit the flat 3-token price before the provider call.
3.  Invoke the Composio ``composio_search`` toolkit.
4.  Normalise the heterogenous result payload into a list of
    :class:`SearchResult` items + an optional summary string.
5.  Attach provider metadata to the structured ``token_usage_logs`` row;
    on provider failure, refund the debit and write a zero-cost audit row.

The service flushes its writes but does **not** commit — the caller
controls the outer transaction, matching every other service in
``app.services``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
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

SERVICE_TYPE: Final[str] = "search"

# Flat 3-token price — see issue #16.
SEARCH_COST: Final[int] = 3

MAX_QUERY_LENGTH: Final[int] = 500
DEFAULT_MAX_RESULTS: Final[int] = 5
MIN_MAX_RESULTS: Final[int] = 1
MAX_MAX_RESULTS: Final[int] = 20


# ----------------------------------------------------------------- errors


class WebSearchError(Exception):
    """Base class for web-search errors."""


class InvalidQueryError(WebSearchError):
    """Raised when the query is missing or too long."""


class InvalidMaxResultsError(WebSearchError):
    """Raised when ``max_results`` is outside the supported range."""


class SearchProviderError(WebSearchError):
    """Raised when the Composio search toolkit fails.

    Exposes ``provider_error`` so the API / bot layer can include the
    upstream message in its response without re-reading the raw payload.
    """

    def __init__(self, message: str, *, provider_error: str | None = None) -> None:
        super().__init__(message)
        self.provider_error = provider_error


# --------------------------------------------------------------- result types


@dataclass(frozen=True)
class SearchResult:
    """One normalised search result row."""

    title: str
    url: str
    snippet: str | None = None
    source: str | None = None


@dataclass(frozen=True)
class WebSearchResult:
    """Outcome of a successful ``search`` call."""

    user_id: int
    query: str
    results: tuple[SearchResult, ...] = field(default_factory=tuple)
    summary: str | None = None
    tokens_spent: int = 0
    new_balance: int = 0
    composio_tool: str = ""
    mcp_server: str | None = None
    processing_time_ms: int | None = None
    usage_log_id: int = 0
    transaction_id: int = 0
    request_id: str | None = None


# ------------------------------------------------------------------ service


class WebSearchService:
    """Service object — instantiate per request with the active session."""

    def __init__(
        self,
        session: AsyncSession,
        composio: ComposioClient,
    ) -> None:
        self.session = session
        self.composio = composio
        self._tokens = TokenService(session, get_default_balance_cache())

    async def search(
        self,
        *,
        user_id: int,
        query: str,
        max_results: int | None = None,
        request_id: str | None = None,
        composio_user_id: str | None = None,
    ) -> WebSearchResult:
        """Run one search query and debit the per-call token cost.

        Raises:
            InvalidQueryError: missing or oversized query.
            InvalidMaxResultsError: ``max_results`` outside the range.
            InsufficientTokensError: balance below :data:`SEARCH_COST`.
            UserNotFoundError: ``user_id`` does not exist.
            SearchProviderError: upstream Composio failure.
        """
        query_clean = self._validate_query(query)
        max_results_clean = self._validate_max_results(max_results)

        request_params: dict[str, Any] = {
            "query": query_clean,
            "max_results": max_results_clean,
        }
        provider_params: dict[str, Any] = dict(request_params)

        spend = await self._tokens.spend(
            user_id=user_id,
            amount=SEARCH_COST,
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
            )
        except SearchProviderError:
            await self._refund_spend(
                user_id=user_id,
                transaction_id=spend.transaction_id,
                reason="search provider failed",
            )
            raise

        results = self._extract_results(result, limit=max_results_clean)
        summary = self._extract_summary(result)

        if not results and not summary:
            await self._refund_spend(
                user_id=user_id,
                transaction_id=spend.transaction_id,
                reason="search provider returned empty result",
            )
            # Audit the failure (zero-cost row) so it surfaces in usage history.
            await log_invocation(
                self.session,
                user_id=user_id,
                result=result,
                tokens_consumed=0,
                request_params=request_params,
            )
            raise SearchProviderError(
                "search provider did not return any results",
                provider_error=result.error,
            )

        await self._record_spend_result(
            user_id=user_id,
            usage_log_id=spend.usage_log_id,
            result=result,
        )

        logger.info(
            "search.completed",
            user_id=user_id,
            query_len=len(query_clean),
            result_count=len(results),
            tokens_spent=SEARCH_COST,
            new_balance=spend.new_balance,
            composio_tool=result.tool,
            mcp_server=result.mcp_server,
            latency_ms=result.latency_ms,
            usage_log_id=spend.usage_log_id,
            transaction_id=spend.transaction_id,
            request_id=request_id,
        )

        return WebSearchResult(
            user_id=user_id,
            query=query_clean,
            results=tuple(results),
            summary=summary,
            tokens_spent=SEARCH_COST,
            new_balance=spend.new_balance,
            composio_tool=result.tool,
            mcp_server=result.mcp_server,
            processing_time_ms=result.latency_ms,
            usage_log_id=spend.usage_log_id,
            transaction_id=spend.transaction_id,
            request_id=request_id,
        )

    # -------------------------------------------------------------- internal

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
                "search.spend_usage_update_failed",
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
                "search.refund_failed",
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
                "search.composio_failed",
                user_id=user_id,
                error=str(exc),
                request_id=request_id,
            )
            raise SearchProviderError(
                "search provider call failed",
                provider_error=str(exc),
            ) from exc

        if not result.successful:
            logger.warning(
                "search.composio_unsuccessful",
                user_id=user_id,
                tool=result.tool,
                error=result.error,
                request_id=request_id,
            )
            raise SearchProviderError(
                f"search provider returned unsuccessful: {result.error or 'unknown'}",
                provider_error=result.error,
            )
        return result

    @staticmethod
    def _extract_results(result: ToolResult, *, limit: int) -> list[SearchResult]:
        """Normalise the Composio response into :class:`SearchResult` rows.

        Toolkits aren't perfectly aligned — different providers return
        ``results``/``items``/``organic`` arrays with varying field names.
        We probe the common keys in order so the service keeps working as
        Composio's search providers evolve.
        """
        data = result.data or {}
        candidates: list[Any] = []
        for key in ("results", "items", "organic", "organic_results", "search_results"):
            value = data.get(key)
            if isinstance(value, list) and value:
                candidates = value
                break

        out: list[SearchResult] = []
        for raw in candidates[:limit]:
            row = _coerce_result_row(raw)
            if row is not None:
                out.append(row)
        return out

    @staticmethod
    def _extract_summary(result: ToolResult) -> str | None:
        """Pull a free-text summary out of the response, if present."""
        data = result.data or {}
        for key in ("summary", "answer", "answer_box", "abstract"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, dict):
                inner = value.get("answer") or value.get("snippet") or value.get("text")
                if isinstance(inner, str) and inner.strip():
                    return inner.strip()
        return None

    # --------------------------------------------------------------- validators

    @staticmethod
    def _validate_query(query: str) -> str:
        if query is None:
            raise InvalidQueryError("query is required")
        clean = str(query).strip()
        if not clean:
            raise InvalidQueryError("query is required")
        if len(clean) > MAX_QUERY_LENGTH:
            raise InvalidQueryError(f"query must be at most {MAX_QUERY_LENGTH} characters")
        return clean

    @staticmethod
    def _validate_max_results(value: int | None) -> int:
        if value is None:
            return DEFAULT_MAX_RESULTS
        try:
            num = int(value)
        except (TypeError, ValueError) as exc:
            raise InvalidMaxResultsError("max_results must be an integer") from exc
        if num < MIN_MAX_RESULTS or num > MAX_MAX_RESULTS:
            raise InvalidMaxResultsError(
                f"max_results must be between {MIN_MAX_RESULTS} and {MAX_MAX_RESULTS}"
            )
        return num


# --------------------------------------------------------------- module helpers


def _coerce_result_row(raw: Any) -> SearchResult | None:
    """Build a :class:`SearchResult` from a heterogeneous payload row."""
    if isinstance(raw, str):
        link = raw.strip()
        if not link:
            return None
        return SearchResult(title=link, url=link)
    if not isinstance(raw, dict):
        return None

    url = None
    for key in ("url", "link", "source_url", "href"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            url = value.strip()
            break
    if url is None:
        return None

    title = None
    for key in ("title", "name", "heading"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            title = value.strip()
            break
    if title is None:
        title = url

    snippet = None
    for key in ("snippet", "description", "summary", "content"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            snippet = value.strip()
            break

    source = None
    for key in ("source", "site", "domain", "provider"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            source = value.strip()
            break

    return SearchResult(title=title, url=url, snippet=snippet, source=source)


__all__ = [
    "DEFAULT_MAX_RESULTS",
    "InvalidMaxResultsError",
    "InvalidQueryError",
    "MAX_MAX_RESULTS",
    "MAX_QUERY_LENGTH",
    "MIN_MAX_RESULTS",
    "SEARCH_COST",
    "SERVICE_TYPE",
    "SearchProviderError",
    "SearchResult",
    "WebSearchError",
    "WebSearchResult",
    "WebSearchService",
]
