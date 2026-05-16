"""Video-generation domain service.

Async sibling of :mod:`app.services.image_generation`.  Video toolkits
take seconds-to-minutes to render, so the flow is:

1.  ``create`` — validate the request, debit tokens up-front, call the
    Composio video toolkit to *submit* a job, persist a ``VideoJob`` row
    holding the provider job id.  Returns immediately so the API / bot
    can show "processing" UI.
2.  ``poll`` — invoked by the polling worker (or the status endpoint
    when the job is still pending) to refresh state.  Calls the same
    toolkit with ``{"job_id": provider_job_id, "action": "status"}``
    and updates the row.  Terminal failure triggers an automatic refund.
3.  ``get`` — read-only fetch by job id; the status endpoint uses this
    and triggers a single inline ``poll`` for non-terminal jobs so the
    UI doesn't have to wait for the worker tick.

The tariff catalog is fixed per issue #14:

* ``short_5s``    — 5s   — 100 tokens
* ``medium_15s``  — 15s  — 250 tokens
* ``long_60s``    — 60s  — 800 tokens
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.video_job import VIDEO_JOB_TERMINAL_STATUSES, VideoJob
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

SERVICE_TYPE: Final[str] = "video"

TARIFF_SHORT: Final[str] = "short_5s"
TARIFF_MEDIUM: Final[str] = "medium_15s"
TARIFF_LONG: Final[str] = "long_60s"

TARIFF_COST: Final[dict[str, int]] = {
    TARIFF_SHORT: 100,
    TARIFF_MEDIUM: 250,
    TARIFF_LONG: 800,
}
TARIFF_DURATION: Final[dict[str, int]] = {
    TARIFF_SHORT: 5,
    TARIFF_MEDIUM: 15,
    TARIFF_LONG: 60,
}
DURATION_TO_TARIFF: Final[dict[int, str]] = {
    duration: tariff for tariff, duration in TARIFF_DURATION.items()
}
SUPPORTED_TARIFFS: Final[frozenset[str]] = frozenset(TARIFF_COST.keys())

MAX_PROMPT_LENGTH: Final[int] = 2000
MAX_STYLE_LENGTH: Final[int] = 100
MAX_REFERENCE_URL_LENGTH: Final[int] = 2000

# Map of upstream provider statuses → our normalised status.
_PROVIDER_STATUS_MAP: Final[dict[str, str]] = {
    "queued": "queued",
    "pending": "queued",
    "submitted": "queued",
    "accepted": "queued",
    "running": "in_progress",
    "processing": "in_progress",
    "in_progress": "in_progress",
    "succeeded": "succeeded",
    "success": "succeeded",
    "completed": "succeeded",
    "done": "succeeded",
    "failed": "failed",
    "error": "failed",
    "canceled": "failed",
    "cancelled": "failed",
    "timeout": "failed",
}


# ----------------------------------------------------------------- errors


class VideoGenerationError(Exception):
    """Base class for video-generation errors."""


class InvalidTariffError(VideoGenerationError):
    """Raised when ``tariff`` (or its ``duration_s`` alias) is unsupported."""


class InvalidPromptError(VideoGenerationError):
    """Raised when the prompt is missing or too long."""


class InvalidReferenceImageError(VideoGenerationError):
    """Raised when ``reference_image_url`` is not a sane http(s) URL."""


class VideoProviderError(VideoGenerationError):
    """Raised when the Composio video toolkit returns a non-recoverable error."""

    def __init__(self, message: str, *, provider_error: str | None = None) -> None:
        super().__init__(message)
        self.provider_error = provider_error


class VideoJobNotFoundError(VideoGenerationError):
    """Raised when ``get`` / ``poll`` is called with an unknown job id."""


# --------------------------------------------------------------- result types


@dataclass(frozen=True)
class VideoJobView:
    """Outward-facing snapshot of a ``video_jobs`` row.

    Kept separate from the ORM model so callers (API / bot / tests) get a
    stable shape and can't accidentally mutate the row.
    """

    id: int
    user_id: int
    request_id: str
    tariff: str
    duration_s: int
    prompt: str
    style: str | None
    reference_image_url: str | None
    status: str
    tokens_cost: int
    provider_job_id: str | None
    composio_tool: str | None
    mcp_server: str | None
    result_url: str | None
    error_code: str | None
    error_message: str | None
    transaction_id: int | None
    refund_transaction_id: int | None
    usage_log_id: int | None
    attempts: int
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None

    @property
    def is_terminal(self) -> bool:
        return self.status in VIDEO_JOB_TERMINAL_STATUSES


def _view(job: VideoJob) -> VideoJobView:
    return VideoJobView(
        id=int(job.id),
        user_id=int(job.user_id),
        request_id=job.request_id,
        tariff=job.tariff,
        duration_s=int(job.duration_s),
        prompt=job.prompt,
        style=job.style,
        reference_image_url=job.reference_image_url,
        status=job.status,
        tokens_cost=int(job.tokens_cost),
        provider_job_id=job.provider_job_id,
        composio_tool=job.composio_tool,
        mcp_server=job.mcp_server,
        result_url=job.result_url,
        error_code=job.error_code,
        error_message=job.error_message,
        transaction_id=int(job.transaction_id) if job.transaction_id else None,
        refund_transaction_id=(
            int(job.refund_transaction_id) if job.refund_transaction_id else None
        ),
        usage_log_id=int(job.usage_log_id) if job.usage_log_id else None,
        attempts=int(job.attempts or 0),
        created_at=job.created_at,
        updated_at=job.updated_at,
        completed_at=job.completed_at,
    )


# ------------------------------------------------------------------ service


class VideoGenerationService:
    """Service object — instantiate per request with the active session."""

    def __init__(
        self,
        session: AsyncSession,
        composio: ComposioClient,
    ) -> None:
        self.session = session
        self.composio = composio
        self._tokens = TokenService(session)

    # ------------------------------------------------------------- create

    async def create(
        self,
        *,
        user_id: int,
        prompt: str,
        tariff: str | None = None,
        duration_s: int | None = None,
        style: str | None = None,
        reference_image_url: str | None = None,
        request_id: str,
        composio_user_id: str | None = None,
    ) -> VideoJobView:
        """Submit a new video-generation job.

        Tokens are debited *before* the provider call so a successful
        Composio submission can never bypass billing.  When the provider
        call fails after the debit, the spend is refunded immediately
        and the row lands in ``failed``/``refunded``.

        Raises:
            InvalidPromptError, InvalidTariffError, InvalidReferenceImageError:
                validation failures.
            InsufficientTokensError: balance below the tariff price.
            UserNotFoundError: ``user_id`` does not exist.
            VideoProviderError: Composio rejected the submission.
        """
        if not request_id:
            raise VideoGenerationError("request_id is required")
        prompt_clean = self._validate_prompt(prompt)
        tariff_clean = self._resolve_tariff(tariff=tariff, duration_s=duration_s)
        style_clean = self._validate_style(style)
        reference_clean = self._validate_reference_url(reference_image_url)
        cost = TARIFF_COST[tariff_clean]
        duration = TARIFF_DURATION[tariff_clean]

        # Idempotency: a Mini-App retry with the same request_id should
        # return the already-created row rather than double-charging.
        existing = await self._find_by_request_id(request_id)
        if existing is not None:
            if existing.user_id != user_id:
                raise VideoGenerationError(
                    f"request_id {request_id!r} belongs to a different user"
                )
            return _view(existing)

        await self._assert_balance_sufficient(user_id, cost)

        spend = await self._tokens.spend(
            user_id=user_id,
            amount=cost,
            service=SERVICE_TYPE,
            request_params={
                "prompt": prompt_clean,
                "tariff": tariff_clean,
                "duration_s": duration,
                "style": style_clean,
                "reference_image_url": reference_clean,
            },
            response_status="pending",
        )

        job = VideoJob(
            user_id=user_id,
            request_id=request_id,
            tariff=tariff_clean,
            duration_s=duration,
            prompt=prompt_clean,
            style=style_clean,
            reference_image_url=reference_clean,
            status="pending",
            tokens_cost=cost,
            transaction_id=spend.transaction_id,
            usage_log_id=spend.usage_log_id,
            attempts=0,
        )
        self.session.add(job)
        await self.session.flush()

        provider_params: dict[str, Any] = {
            "prompt": prompt_clean,
            "duration_s": duration,
            "tariff": tariff_clean,
        }
        if style_clean is not None:
            provider_params["style"] = style_clean
        if reference_clean is not None:
            provider_params["reference_image_url"] = reference_clean

        try:
            submission = await self._submit_provider(
                user_id=user_id,
                params=provider_params,
                request_id=request_id,
                composio_user_id=composio_user_id,
            )
        except VideoProviderError as exc:
            await self._apply_failure(
                job,
                error_code="submit_failed",
                error_message=str(exc),
                provider_error=exc.provider_error,
                refund_reason="video submit failed",
            )
            await self.session.flush()
            raise

        job.composio_tool = submission.tool
        job.mcp_server = submission.mcp_server
        job.attempts = (job.attempts or 0) + 1
        job.provider_job_id = self._extract_provider_job_id(submission)
        normalised = self._normalise_status(submission)
        url = self._extract_url(submission)

        if normalised == "succeeded" and url:
            await self._apply_success(job, url, submission)
        elif normalised == "failed":
            await self._apply_failure(
                job,
                error_code="submit_rejected",
                error_message=submission.error or "provider rejected submission",
                provider_error=submission.error,
                refund_reason="video submit rejected",
            )
        else:
            job.status = normalised or "queued"
            job.updated_at = datetime.now(UTC)

        await self.session.flush()

        logger.info(
            "video.created",
            user_id=user_id,
            job_id=job.id,
            tariff=tariff_clean,
            tokens_cost=cost,
            status=job.status,
            provider_job_id=job.provider_job_id,
            composio_tool=submission.tool,
            request_id=request_id,
        )
        return _view(job)

    # ------------------------------------------------------------- get / poll

    async def get(self, job_id: int, *, user_id: int | None = None) -> VideoJobView:
        """Fetch a job snapshot.

        ``user_id``, when provided, restricts the lookup to that owner —
        the API uses it to prevent cross-user reads.
        """
        job = await self._load(job_id, user_id=user_id)
        return _view(job)

    async def get_and_refresh(
        self,
        job_id: int,
        *,
        user_id: int | None = None,
        composio_user_id: str | None = None,
    ) -> VideoJobView:
        """Fetch a job and trigger one inline poll if still running.

        The status endpoint uses this so the UI can show "succeeded"
        without waiting for the worker tick.
        """
        job = await self._load(job_id, user_id=user_id)
        if job.status in VIDEO_JOB_TERMINAL_STATUSES:
            return _view(job)
        await self._poll_job(job, composio_user_id=composio_user_id)
        return _view(job)

    async def poll(
        self,
        job_id: int,
        *,
        composio_user_id: str | None = None,
    ) -> VideoJobView:
        """Worker entrypoint — poll a single job and persist the new state."""
        job = await self._load(job_id)
        if job.status in VIDEO_JOB_TERMINAL_STATUSES:
            return _view(job)
        await self._poll_job(job, composio_user_id=composio_user_id)
        return _view(job)

    async def list_active(
        self,
        *,
        limit: int = 100,
    ) -> list[VideoJobView]:
        """Return non-terminal jobs in oldest-first order for the worker."""
        stmt = (
            select(VideoJob)
            .where(VideoJob.status.in_(("pending", "queued", "in_progress")))
            .order_by(VideoJob.updated_at.asc())
            .limit(max(int(limit or 1), 1))
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_view(r) for r in rows]

    # -------------------------------------------------------------- internal

    async def _poll_job(
        self,
        job: VideoJob,
        *,
        composio_user_id: str | None,
    ) -> None:
        params: dict[str, Any] = {
            "action": "status",
            "job_id": job.provider_job_id or "",
        }
        try:
            result = await self.composio.invoke_for_service(
                SERVICE_TYPE,
                params,
                user_id=composio_user_id,
                request_id=job.request_id,
                metadata={
                    "app_user_id": str(job.user_id),
                    "video_job_id": str(job.id),
                    "phase": "poll",
                },
            )
        except ComposioError as exc:
            logger.warning(
                "video.poll_failed",
                user_id=job.user_id,
                job_id=job.id,
                error=str(exc),
            )
            job.attempts = (job.attempts or 0) + 1
            job.error_message = str(exc)
            job.updated_at = datetime.now(UTC)
            await self.session.flush()
            return

        job.attempts = (job.attempts or 0) + 1
        if result.mcp_server and not job.mcp_server:
            job.mcp_server = result.mcp_server
        if result.tool and not job.composio_tool:
            job.composio_tool = result.tool

        if not result.successful:
            await self._apply_failure(
                job,
                error_code="provider_unsuccessful",
                error_message=result.error or "provider returned unsuccessful",
                provider_error=result.error,
                refund_reason="video poll unsuccessful",
            )
            await self.session.flush()
            return

        normalised = self._normalise_status(result)
        url = self._extract_url(result)

        if normalised == "succeeded" and url:
            await self._apply_success(job, url, result)
        elif normalised == "failed":
            await self._apply_failure(
                job,
                error_code="provider_failed",
                error_message=result.error or "provider reported failure",
                provider_error=result.error,
                refund_reason="video generation failed",
            )
        else:
            job.status = normalised or job.status or "queued"
            job.updated_at = datetime.now(UTC)
        await self.session.flush()

    async def _apply_success(
        self,
        job: VideoJob,
        url: str,
        result: ToolResult,
    ) -> None:
        job.status = "succeeded"
        job.result_url = url
        job.error_code = None
        job.error_message = None
        job.completed_at = datetime.now(UTC)
        job.updated_at = job.completed_at
        if result.mcp_server and not job.mcp_server:
            job.mcp_server = result.mcp_server
        logger.info(
            "video.succeeded",
            user_id=job.user_id,
            job_id=job.id,
            tokens_cost=job.tokens_cost,
            composio_tool=job.composio_tool,
            mcp_server=job.mcp_server,
        )

    async def _apply_failure(
        self,
        job: VideoJob,
        *,
        error_code: str,
        error_message: str | None,
        provider_error: str | None,
        refund_reason: str,
    ) -> None:
        """Mark a job as failed and refund the up-front spend.

        Audit-only: also writes a zero-cost ``token_usage_logs`` row via
        :func:`log_invocation` so the failure surfaces in admin history
        even though no tokens are net-debited.
        """
        job.status = "failed"
        job.error_code = error_code
        job.error_message = error_message
        job.completed_at = datetime.now(UTC)
        job.updated_at = job.completed_at
        try:
            audit = await log_invocation(
                self.session,
                user_id=job.user_id,
                result=ToolResult(
                    tool=job.composio_tool or "video_gen",
                    successful=False,
                    data={},
                    error=provider_error,
                    service_type=SERVICE_TYPE,
                    mcp_server=job.mcp_server,
                ),
                tokens_consumed=0,
                request_params={
                    "video_job_id": job.id,
                    "tariff": job.tariff,
                    "error_code": error_code,
                },
            )
            logger.debug("video.failure_audit_logged", usage_log_id=audit.id)
        except Exception as exc:  # noqa: BLE001 — audit logging is best-effort
            logger.warning("video.failure_audit_failed", error=str(exc))

        if job.transaction_id is None or job.refund_transaction_id is not None:
            return
        try:
            refund = await self._tokens.refund(
                transaction_id=int(job.transaction_id),
                reason=refund_reason[:100],
            )
        except Exception as exc:  # noqa: BLE001 — never let refund failure mask the user-facing error
            logger.warning(
                "video.refund_failed",
                user_id=job.user_id,
                job_id=job.id,
                error=str(exc),
            )
            return
        job.refund_transaction_id = refund.transaction_id
        job.status = "refunded"
        logger.info(
            "video.refunded",
            user_id=job.user_id,
            job_id=job.id,
            tokens=job.tokens_cost,
            transaction_id=job.transaction_id,
            refund_transaction_id=refund.transaction_id,
            reason=refund_reason,
        )

    async def _submit_provider(
        self,
        *,
        user_id: int,
        params: dict[str, Any],
        request_id: str,
        composio_user_id: str | None,
    ) -> ToolResult:
        try:
            result = await self.composio.invoke_for_service(
                SERVICE_TYPE,
                {**params, "action": "submit"},
                user_id=composio_user_id,
                request_id=request_id,
                metadata={
                    "app_user_id": str(user_id),
                    "phase": "submit",
                },
            )
        except ComposioError as exc:
            logger.warning(
                "video.composio_failed",
                user_id=user_id,
                error=str(exc),
                request_id=request_id,
            )
            raise VideoProviderError(
                "video provider call failed",
                provider_error=str(exc),
            ) from exc

        if not result.successful:
            logger.warning(
                "video.composio_unsuccessful",
                user_id=user_id,
                tool=result.tool,
                error=result.error,
                request_id=request_id,
            )
            raise VideoProviderError(
                f"video provider returned unsuccessful: {result.error or 'unknown'}",
                provider_error=result.error,
            )
        return result

    async def _assert_balance_sufficient(self, user_id: int, cost: int) -> None:
        try:
            balance = await self._tokens.get_balance(user_id)
        except UserNotFoundError:
            raise
        if balance < cost:
            raise InsufficientTokensError(required=cost, available=balance)

    async def _find_by_request_id(self, request_id: str) -> VideoJob | None:
        stmt = select(VideoJob).where(VideoJob.request_id == request_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _load(self, job_id: int, *, user_id: int | None = None) -> VideoJob:
        stmt = select(VideoJob).where(VideoJob.id == job_id)
        if user_id is not None:
            stmt = stmt.where(VideoJob.user_id == user_id)
        job = (await self.session.execute(stmt)).scalar_one_or_none()
        if job is None:
            raise VideoJobNotFoundError(f"video job {job_id} not found")
        return job

    # ---------------------------------------------------------- normalisers

    @staticmethod
    def _normalise_status(result: ToolResult) -> str | None:
        """Map an upstream status field onto our internal vocabulary.

        Returns ``None`` when the response has no status hint — callers
        then treat the job as still queued.
        """
        data = result.data or {}
        for key in ("status", "state", "job_status"):
            raw = data.get(key)
            if isinstance(raw, str) and raw.strip():
                normalised = _PROVIDER_STATUS_MAP.get(raw.strip().lower())
                if normalised:
                    return normalised
        if isinstance(data.get("error"), str) and data["error"].strip():
            return "failed"
        return None

    @staticmethod
    def _extract_provider_job_id(result: ToolResult) -> str | None:
        data = result.data or {}
        for key in ("job_id", "id", "task_id", "operation_id"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _extract_url(result: ToolResult) -> str | None:
        """Pull the result URL from the Composio response.

        Different toolkits return ``url`` / ``video_url`` / ``result_url``
        and sometimes nest under ``videos[0]`` or ``output.url`` — handle
        each shape we've seen in the wild.
        """
        data = result.data or {}
        for key in ("video_url", "url", "result_url", "output_url"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        videos = data.get("videos")
        if isinstance(videos, list) and videos:
            first = videos[0]
            if isinstance(first, str) and first.strip():
                return first.strip()
            if isinstance(first, dict):
                for key in ("url", "video_url", "result_url"):
                    value = first.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()

        output = data.get("output")
        if isinstance(output, dict):
            for key in ("video_url", "url", "result_url"):
                value = output.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return None

    # --------------------------------------------------------------- validators

    @staticmethod
    def _resolve_tariff(*, tariff: str | None, duration_s: int | None) -> str:
        """Resolve a tariff from ``tariff`` (preferred) or ``duration_s``.

        Both knobs ship in the API per #14 — ``tariff`` is the explicit
        catalog key; ``duration_s`` is the human-friendly alias.  If both
        are given they must agree.  Either may be omitted (the other is
        sufficient).
        """
        tariff_clean: str | None = None
        if tariff is not None:
            tariff_str = str(tariff).strip().lower()
            if tariff_str:
                if tariff_str not in SUPPORTED_TARIFFS:
                    raise InvalidTariffError(
                        f"tariff must be one of {sorted(SUPPORTED_TARIFFS)}"
                    )
                tariff_clean = tariff_str

        if duration_s is not None:
            try:
                dur_int = int(duration_s)
            except (TypeError, ValueError) as exc:
                raise InvalidTariffError("duration_s must be an integer") from exc
            mapped = DURATION_TO_TARIFF.get(dur_int)
            if mapped is None:
                raise InvalidTariffError(
                    f"duration_s must be one of {sorted(DURATION_TO_TARIFF)}"
                )
            if tariff_clean is not None and tariff_clean != mapped:
                raise InvalidTariffError(
                    f"duration_s={dur_int} does not match tariff {tariff_clean!r}"
                )
            tariff_clean = mapped

        if tariff_clean is None:
            tariff_clean = TARIFF_SHORT
        return tariff_clean

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
    def _validate_style(value: str | None) -> str | None:
        if value is None:
            return None
        clean = str(value).strip()
        if not clean:
            return None
        if len(clean) > MAX_STYLE_LENGTH:
            raise VideoGenerationError(
                f"style must be at most {MAX_STYLE_LENGTH} characters"
            )
        return clean

    @staticmethod
    def _validate_reference_url(value: str | None) -> str | None:
        if value is None:
            return None
        clean = str(value).strip()
        if not clean:
            return None
        if len(clean) > MAX_REFERENCE_URL_LENGTH:
            raise InvalidReferenceImageError(
                f"reference_image_url must be at most {MAX_REFERENCE_URL_LENGTH} characters"
            )
        lower = clean.lower()
        if not (lower.startswith("http://") or lower.startswith("https://")):
            raise InvalidReferenceImageError(
                "reference_image_url must be an http(s) URL"
            )
        return clean


__all__ = [
    "DURATION_TO_TARIFF",
    "InvalidPromptError",
    "InvalidReferenceImageError",
    "InvalidTariffError",
    "MAX_PROMPT_LENGTH",
    "MAX_REFERENCE_URL_LENGTH",
    "MAX_STYLE_LENGTH",
    "SERVICE_TYPE",
    "SUPPORTED_TARIFFS",
    "TARIFF_COST",
    "TARIFF_DURATION",
    "TARIFF_LONG",
    "TARIFF_MEDIUM",
    "TARIFF_SHORT",
    "VideoGenerationError",
    "VideoGenerationService",
    "VideoJobNotFoundError",
    "VideoJobView",
    "VideoProviderError",
]
