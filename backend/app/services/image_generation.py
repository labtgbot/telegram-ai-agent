"""Image-generation domain service.

Orchestrates a single image-generation request end-to-end:

1.  Validate the request shape (quality, aspect ratio, prompt length).
2.  Pre-check the user's token balance against the per-quality cost so
    the caller learns about insufficient funds *before* we burn a
    Composio call.
3.  Invoke the Composio ``image_gen`` toolkit (or whichever provider
    ``service_type='image'`` resolves to — operators can override via
    admin settings).
4.  On success, atomically debit the cost via :class:`TokenService.spend`
    and record a structured row in ``token_usage_logs``; on failure,
    insert an audit-only row (no debit) so admins can see the error in
    the usage history.

Both the HTTP endpoint (``POST /api/v1/generate/image``) and the bot
command (``/image``) call into this service so the cost model, the
audit shape and the error semantics stay in one place.  The service
flushes its writes but does **not** commit — the caller controls the
outer transaction, matching the pattern used by every other service in
``app.services``.
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
from app.services.token_service import (
    InsufficientTokensError,
    TokenService,
    UserNotFoundError,
)

logger = get_logger(__name__)


# ----------------------------------------------------------------- constants

SERVICE_TYPE: Final[str] = "image"

QUALITY_STANDARD: Final[str] = "standard"
QUALITY_HD: Final[str] = "hd"
QUALITY_ULTRA_HD: Final[str] = "ultra_hd"

QUALITY_COST: Final[dict[str, int]] = {
    QUALITY_STANDARD: 30,
    QUALITY_HD: 50,
    QUALITY_ULTRA_HD: 100,
}
SUPPORTED_QUALITIES: Final[frozenset[str]] = frozenset(QUALITY_COST.keys())

DEFAULT_ASPECT_RATIO: Final[str] = "1:1"
SUPPORTED_ASPECT_RATIOS: Final[frozenset[str]] = frozenset(
    {"1:1", "3:2", "2:3", "4:3", "3:4", "16:9", "9:16"}
)

MAX_PROMPT_LENGTH: Final[int] = 2000
MAX_NEGATIVE_PROMPT_LENGTH: Final[int] = 1000


# ----------------------------------------------------------------- errors


class ImageGenerationError(Exception):
    """Base class for image-generation errors."""


class InvalidQualityError(ImageGenerationError):
    """Raised when ``quality`` is not one of :data:`SUPPORTED_QUALITIES`."""


class InvalidAspectRatioError(ImageGenerationError):
    """Raised when ``aspect_ratio`` is outside :data:`SUPPORTED_ASPECT_RATIOS`."""


class InvalidPromptError(ImageGenerationError):
    """Raised when the prompt is missing or too long."""


class ImageProviderError(ImageGenerationError):
    """Raised when the Composio image toolkit returns a non-recoverable error.

    Exposes ``provider_error`` so the API / bot layer can include the
    upstream message in its response without re-reading the raw payload.
    """

    def __init__(self, message: str, *, provider_error: str | None = None) -> None:
        super().__init__(message)
        self.provider_error = provider_error


# --------------------------------------------------------------- result types


@dataclass(frozen=True)
class ImageGenerationResult:
    """Outcome of a successful generation call.

    ``usage_log_id`` and ``transaction_id`` point at the ledger rows so
    the caller can echo them in the API response and, eventually, in
    Mini-App "view in history" deep-links.
    """

    user_id: int
    prompt: str
    quality: str
    aspect_ratio: str
    tokens_spent: int
    new_balance: int
    result_url: str
    composio_tool: str
    mcp_server: str | None
    processing_time_ms: int | None
    usage_log_id: int
    transaction_id: int
    request_id: str | None = None


# ------------------------------------------------------------------ service


class ImageGenerationService:
    """Service object — instantiate per request with the active session.

    The service is intentionally stateless: every call carries its own
    ``user_id`` and parameters so the same instance can serve multiple
    requests in a worker if a future Celery task ever wants to reuse it.
    """

    def __init__(
        self,
        session: AsyncSession,
        composio: ComposioClient,
    ) -> None:
        self.session = session
        self.composio = composio
        self._tokens = TokenService(session)

    async def generate(
        self,
        *,
        user_id: int,
        prompt: str,
        quality: str = QUALITY_STANDARD,
        aspect_ratio: str | None = None,
        negative_prompt: str | None = None,
        request_id: str | None = None,
        composio_user_id: str | None = None,
    ) -> ImageGenerationResult:
        """Generate one image and debit the user's token balance.

        Raises:
            InvalidPromptError: empty or too-long prompt.
            InvalidQualityError: unknown quality tier.
            InvalidAspectRatioError: aspect ratio outside the catalog.
            InsufficientTokensError: balance below the quality price.
            UserNotFoundError: ``user_id`` does not exist.
            ImageProviderError: upstream Composio failure
                (transport / 5xx / business-level ``successful=False``).
        """
        prompt_clean = self._validate_prompt(prompt)
        quality_clean = self._validate_quality(quality)
        aspect_clean = self._validate_aspect_ratio(aspect_ratio)
        negative_clean = self._validate_negative_prompt(negative_prompt)
        cost = QUALITY_COST[quality_clean]

        await self._assert_balance_sufficient(user_id, cost)

        request_params: dict[str, Any] = {
            "prompt": prompt_clean,
            "quality": quality_clean,
            "aspect_ratio": aspect_clean,
        }
        if negative_clean is not None:
            request_params["negative_prompt"] = negative_clean

        provider_params: dict[str, Any] = dict(request_params)

        result = await self._invoke_provider(
            user_id=user_id,
            params=provider_params,
            request_id=request_id,
            composio_user_id=composio_user_id,
        )

        url = self._extract_url(result)
        if url is None:
            # Audit the failure (zero-cost row) so it surfaces in usage history.
            await log_invocation(
                self.session,
                user_id=user_id,
                result=result,
                tokens_consumed=0,
                request_params=request_params,
            )
            raise ImageProviderError(
                "image provider did not return a URL",
                provider_error=result.error,
            )

        spend = await self._tokens.spend(
            user_id=user_id,
            amount=cost,
            service=SERVICE_TYPE,
            request_params=request_params,
            response_status="ok",
            processing_time_ms=result.latency_ms,
            composio_tool=result.tool,
            mcp_server=result.mcp_server,
        )

        logger.info(
            "image.generated",
            user_id=user_id,
            quality=quality_clean,
            aspect_ratio=aspect_clean,
            tokens_spent=cost,
            new_balance=spend.new_balance,
            composio_tool=result.tool,
            mcp_server=result.mcp_server,
            latency_ms=result.latency_ms,
            usage_log_id=spend.usage_log_id,
            transaction_id=spend.transaction_id,
            request_id=request_id,
        )

        return ImageGenerationResult(
            user_id=user_id,
            prompt=prompt_clean,
            quality=quality_clean,
            aspect_ratio=aspect_clean,
            tokens_spent=cost,
            new_balance=spend.new_balance,
            result_url=url,
            composio_tool=result.tool,
            mcp_server=result.mcp_server,
            processing_time_ms=result.latency_ms,
            usage_log_id=spend.usage_log_id,
            transaction_id=spend.transaction_id,
            request_id=request_id,
        )

    # -------------------------------------------------------------- internal

    async def _assert_balance_sufficient(self, user_id: int, cost: int) -> None:
        """Pre-flight balance check.

        Reading the balance without a row lock here is intentional —
        the authoritative check happens inside :meth:`TokenService.spend`
        under ``SELECT ... FOR UPDATE``.  This early probe just lets us
        skip the (paid, slow) Composio call when the user can't afford
        the request.
        """
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
                "image.composio_failed",
                user_id=user_id,
                error=str(exc),
                request_id=request_id,
            )
            raise ImageProviderError(
                "image provider call failed",
                provider_error=str(exc),
            ) from exc

        if not result.successful:
            logger.warning(
                "image.composio_unsuccessful",
                user_id=user_id,
                tool=result.tool,
                error=result.error,
                request_id=request_id,
            )
            raise ImageProviderError(
                f"image provider returned unsuccessful: {result.error or 'unknown'}",
                provider_error=result.error,
            )
        return result

    @staticmethod
    def _extract_url(result: ToolResult) -> str | None:
        """Pull the result URL from the Composio response.

        Composio toolkits aren't perfectly consistent yet — different
        providers return ``url`` / ``image_url`` / ``result_url`` and
        sometimes nest under ``images[0].url``.  We try the common keys
        in order so the service keeps working as toolkits evolve.
        """
        data = result.data or {}
        for key in ("url", "image_url", "result_url", "output_url"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        images = data.get("images")
        if isinstance(images, list) and images:
            first = images[0]
            if isinstance(first, str) and first.strip():
                return first.strip()
            if isinstance(first, dict):
                for key in ("url", "image_url", "result_url"):
                    value = first.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
        return None

    @staticmethod
    def _validate_prompt(prompt: str) -> str:
        if prompt is None:
            raise InvalidPromptError("prompt is required")
        clean = str(prompt).strip()
        if not clean:
            raise InvalidPromptError("prompt is required")
        if len(clean) > MAX_PROMPT_LENGTH:
            raise InvalidPromptError(
                f"prompt must be at most {MAX_PROMPT_LENGTH} characters"
            )
        return clean

    @staticmethod
    def _validate_negative_prompt(value: str | None) -> str | None:
        if value is None:
            return None
        clean = str(value).strip()
        if not clean:
            return None
        if len(clean) > MAX_NEGATIVE_PROMPT_LENGTH:
            raise InvalidPromptError(
                f"negative_prompt must be at most {MAX_NEGATIVE_PROMPT_LENGTH} "
                "characters"
            )
        return clean

    @staticmethod
    def _validate_quality(quality: str) -> str:
        if quality is None:
            raise InvalidQualityError("quality is required")
        clean = str(quality).strip().lower()
        if clean not in SUPPORTED_QUALITIES:
            raise InvalidQualityError(
                f"quality must be one of {sorted(SUPPORTED_QUALITIES)}"
            )
        return clean

    @staticmethod
    def _validate_aspect_ratio(value: str | None) -> str:
        if value is None or not str(value).strip():
            return DEFAULT_ASPECT_RATIO
        clean = str(value).strip()
        if clean not in SUPPORTED_ASPECT_RATIOS:
            raise InvalidAspectRatioError(
                f"aspect_ratio must be one of {sorted(SUPPORTED_ASPECT_RATIOS)}"
            )
        return clean


__all__ = [
    "DEFAULT_ASPECT_RATIO",
    "ImageGenerationError",
    "ImageGenerationResult",
    "ImageGenerationService",
    "ImageProviderError",
    "InvalidAspectRatioError",
    "InvalidPromptError",
    "InvalidQualityError",
    "MAX_NEGATIVE_PROMPT_LENGTH",
    "MAX_PROMPT_LENGTH",
    "QUALITY_COST",
    "QUALITY_HD",
    "QUALITY_STANDARD",
    "QUALITY_ULTRA_HD",
    "SERVICE_TYPE",
    "SUPPORTED_ASPECT_RATIOS",
    "SUPPORTED_QUALITIES",
]
