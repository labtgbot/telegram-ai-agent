"""AI generation endpoints.

* ``POST /api/v1/generate/image`` — synchronously generate an image via
  the Composio image toolkit and debit tokens by quality tier.
* ``POST /api/v1/generate/video`` — submit an asynchronous video job
  (provider returns a job id immediately) and debit tokens by tariff.
* ``GET  /api/v1/generate/video/{job_id}`` — poll a video job's status
  (returns the final URL when ready, refund details on failure).
* ``POST /api/v1/generate/text`` — synchronous text generation in one of
  three modes (basic/advanced/autonomous_agent); returns the final
  response in a single JSON body.
* ``POST /api/v1/generate/text/stream`` — same call but server-sends the
  response as SSE so the Mini-App can render a typewriter effect.
* ``POST /api/v1/generate/search`` — web search via the Composio search
  toolkit; returns structured results plus an optional summary.
* ``POST /api/v1/generate/voice`` — voice message: STT for incoming audio,
  optional TTS to synthesise a reply.
* ``POST /api/v1/generate/document`` — document analysis (PDF/DOCX/TXT)
  with text extraction, summary and optional Q&A.

The endpoints require a valid ``X-Telegram-Init-Data`` header (Mini-App
flow) and are rate-limited via the ``image`` / ``video`` / ``text`` /
``search`` / ``voice`` / ``document`` quota buckets defined in
``app.services.rate_limit_config``.

Token cost / quality tiers (mirrors ``ImageGenerationService``):

* ``standard``   →  30 tokens
* ``hd``         →  50 tokens
* ``ultra_hd``   → 100 tokens

Video tariffs (mirrors ``VideoGenerationService``):

* ``short_5s``    →  5s →  100 tokens
* ``medium_15s``  → 15s →  250 tokens
* ``long_60s``    → 60s →  800 tokens

Text modes (mirrors ``TextGenerationService``):

* ``basic``               →  1 token  → Gemini.
* ``advanced``            →  5 tokens → Claude.
* ``autonomous_agent``    → 10 tokens → GPT.

Phase 2 service prices (issue #16):

* ``search``    →  3 tokens (flat)
* ``voice``     →  5 tokens (flat; STT and STT+TTS both)
* ``document``  → 20 tokens (flat; 10 MB free / 50 MB premium upload cap)
"""
from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator

from app.api.rate_limit import rate_limit
from app.auth.dependencies import SessionDep, get_current_user_from_init_data
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.models.user import User
from app.services.composio import (
    ComposioClient,
    build_client,
)
from app.services.document_analysis import (
    DOCUMENT_COST,
    MAX_DOCUMENT_URL_LENGTH,
    MAX_FILE_BYTES_FREE,
    MAX_FILE_BYTES_PREMIUM,
    MAX_FILENAME_LENGTH,
    MAX_QUESTION_LENGTH,
    SUPPORTED_FORMATS,
    DocumentAnalysisService,
    DocumentProviderError,
    DocumentTooLargeError,
    InvalidDocumentError,
    InvalidDocumentFormatError,
    InvalidQuestionError,
)
from app.services.image_generation import (
    DEFAULT_ASPECT_RATIO,
    MAX_NEGATIVE_PROMPT_LENGTH,
    MAX_PROMPT_LENGTH,
    QUALITY_COST,
    ImageGenerationService,
    ImageProviderError,
    InvalidAspectRatioError,
    InvalidPromptError,
    InvalidQualityError,
)
from app.services.text_generation import (
    MAX_PROMPT_LENGTH as MAX_TEXT_PROMPT_LENGTH,
)
from app.services.text_generation import (
    MAX_SYSTEM_PROMPT_LENGTH as MAX_TEXT_SYSTEM_PROMPT_LENGTH,
)
from app.services.text_generation import (
    MODE_BASIC,
    MODE_COST,
    SUPPORTED_MODES,
    ConversationHistory,
    DbConversationHistory,
    InvalidMaxTokensError,
    InvalidModeError,
    InvalidTemperatureError,
    RedisConversationHistory,
    TextGenerationResult,
    TextGenerationService,
    TextProviderError,
)
from app.services.text_generation import (
    InvalidPromptError as TextInvalidPromptError,
)
from app.services.token_service import (
    InsufficientTokensError,
    UserNotFoundError,
)
from app.services.video_generation import (
    DURATION_TO_TARIFF,
    MAX_REFERENCE_URL_LENGTH,
    MAX_STYLE_LENGTH,
    SUPPORTED_TARIFFS,
    TARIFF_COST,
    TARIFF_DURATION,
    InvalidReferenceImageError,
    InvalidTariffError,
    VideoGenerationError,
    VideoGenerationService,
    VideoJobNotFoundError,
    VideoJobView,
    VideoProviderError,
)
from app.services.video_generation import (
    MAX_PROMPT_LENGTH as MAX_VIDEO_PROMPT_LENGTH,
)
from app.services.video_generation import (
    InvalidPromptError as VideoInvalidPromptError,
)
from app.services.voice_processing import (
    MAX_AUDIO_URL_LENGTH,
    MAX_LANGUAGE_LENGTH,
    MAX_VOICE_LENGTH,
    VOICE_COST,
    InvalidAudioError,
    InvalidVoicePromptError,
    VoiceProcessingService,
    VoiceProviderError,
)
from app.services.voice_processing import (
    MAX_PROMPT_LENGTH as MAX_VOICE_PROMPT_LENGTH,
)
from app.services.web_search import (
    MAX_MAX_RESULTS,
    MAX_QUERY_LENGTH,
    MIN_MAX_RESULTS,
    SEARCH_COST,
    InvalidMaxResultsError,
    SearchProviderError,
    WebSearchService,
)
from app.services.web_search import (
    InvalidQueryError as SearchInvalidQueryError,
)

router = APIRouter(prefix="/generate", tags=["generate"])
logger = get_logger(__name__)


# --------------------------------------------------------- composio dependency

_composio_client_singleton: ComposioClient | None = None


def get_composio_client() -> ComposioClient:
    """Return a process-wide :class:`ComposioClient`.

    The factory in :func:`app.services.composio.build_client` already
    picks the mock client when credentials are missing — we just cache
    the instance so the underlying ``httpx.AsyncClient`` is reused
    across requests.
    """
    global _composio_client_singleton
    if _composio_client_singleton is None:
        _composio_client_singleton = build_client()
    return _composio_client_singleton


async def close_composio_client() -> None:
    """Close the cached client at shutdown."""
    global _composio_client_singleton
    if _composio_client_singleton is not None:
        await _composio_client_singleton.aclose()
        _composio_client_singleton = None


def reset_composio_client() -> None:
    """Drop the cached client without closing it (test helper)."""
    global _composio_client_singleton
    _composio_client_singleton = None


ComposioClientDep = Annotated[ComposioClient, Depends(get_composio_client)]


# ----------------------------------------------------------------- schemas


_Quality = Literal["standard", "hd", "ultra_hd"]


class ImageGenerationRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=MAX_PROMPT_LENGTH)
    quality: _Quality = "standard"
    aspect_ratio: str = Field(
        default=DEFAULT_ASPECT_RATIO,
        min_length=1,
        max_length=16,
        description="Image aspect ratio, e.g. '1:1', '16:9', '9:16'.",
    )
    negative_prompt: str | None = Field(
        default=None,
        max_length=MAX_NEGATIVE_PROMPT_LENGTH,
        description="Optional negative prompt — concepts to avoid.",
    )


class ImageGenerationResponse(BaseModel):
    result_url: str
    prompt: str
    quality: _Quality
    aspect_ratio: str
    tokens_spent: int
    new_balance: int
    usage_log_id: int
    transaction_id: int
    request_id: str
    composio_tool: str
    processing_time_ms: int | None = None


# ----------------------------------------------------------------- endpoint


@router.post(
    "/image",
    response_model=ImageGenerationResponse,
    summary="Generate an image and debit tokens by quality tier",
    dependencies=[Depends(rate_limit(action="image"))],
)
async def generate_image(
    body: ImageGenerationRequest,
    session: SessionDep,
    composio: ComposioClientDep,
    user: Annotated[User, Depends(get_current_user_from_init_data)],
) -> ImageGenerationResponse:
    """Synchronous image generation via the Composio image toolkit.

    Failure modes:

    * ``400 invalid_quality`` / ``invalid_aspect_ratio`` / ``invalid_prompt``
    * ``402 insufficient_tokens`` — balance below the quality price
    * ``502 image_provider_error`` — Composio call failed / no URL
    * ``500 commit_failed`` — DB error on commit
    """
    service = ImageGenerationService(session, composio)
    request_id = uuid.uuid4().hex

    try:
        outcome = await service.generate(
            user_id=user.id,
            prompt=body.prompt,
            quality=body.quality,
            aspect_ratio=body.aspect_ratio,
            negative_prompt=body.negative_prompt,
            request_id=request_id,
        )
    except InvalidPromptError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_prompt", "message": str(exc)},
        ) from exc
    except InvalidQualityError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "invalid_quality",
                "message": str(exc),
                "supported": sorted(QUALITY_COST.keys()),
            },
        ) from exc
    except InvalidAspectRatioError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_aspect_ratio", "message": str(exc)},
        ) from exc
    except InsufficientTokensError as exc:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "insufficient_tokens",
                "required": exc.required,
                "available": exc.available,
            },
        ) from exc
    except UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="user_not_found",
        ) from exc
    except ImageProviderError as exc:
        await session.rollback()
        logger.warning(
            "generate.image.provider_error",
            user_id=user.id,
            request_id=request_id,
            error=str(exc),
            provider_error=exc.provider_error,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "image_provider_error",
                "message": str(exc),
                "provider_error": exc.provider_error,
            },
        ) from exc

    try:
        await session.commit()
    except Exception as exc:  # noqa: BLE001 — surface a clean 500
        await session.rollback()
        logger.exception(
            "generate.image.commit_failed",
            user_id=user.id,
            request_id=request_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="commit_failed",
        ) from exc

    return ImageGenerationResponse(
        result_url=outcome.result_url,
        prompt=outcome.prompt,
        quality=outcome.quality,  # type: ignore[arg-type]
        aspect_ratio=outcome.aspect_ratio,
        tokens_spent=outcome.tokens_spent,
        new_balance=outcome.new_balance,
        usage_log_id=outcome.usage_log_id,
        transaction_id=outcome.transaction_id,
        request_id=request_id,
        composio_tool=outcome.composio_tool,
        processing_time_ms=outcome.processing_time_ms,
    )


# --------------------------------------------------------------- video schemas


_VideoTariff = Literal["short_5s", "medium_15s", "long_60s"]
_VideoStatus = Literal[
    "pending", "queued", "in_progress", "succeeded", "failed", "refunded"
]


class VideoGenerationRequest(BaseModel):
    """Video-generation request body.

    Either ``tariff`` or ``duration_s`` must identify the tariff; when both
    are supplied they must agree. Per issue #14: 5s/15s/60s tariffs.
    """

    prompt: str = Field(..., min_length=1, max_length=MAX_VIDEO_PROMPT_LENGTH)
    tariff: _VideoTariff | None = None
    duration_s: int | None = Field(
        default=None,
        description=(
            "Video length in seconds. One of 5, 15, 60. Equivalent to "
            "selecting tariff short_5s / medium_15s / long_60s."
        ),
    )
    style: str | None = Field(
        default=None,
        max_length=MAX_STYLE_LENGTH,
        description="Optional style hint passed to the provider.",
    )
    reference_image_url: str | None = Field(
        default=None,
        max_length=MAX_REFERENCE_URL_LENGTH,
        description="Optional http(s) URL to a reference image.",
    )

    @model_validator(mode="after")
    def _require_tariff_or_duration(self) -> VideoGenerationRequest:
        if self.tariff is None and self.duration_s is None:
            # The service defaults to ``short_5s`` when neither is set, but
            # we want callers to make an explicit choice for billing clarity.
            pass
        return self


class VideoJobResponse(BaseModel):
    """Snapshot of a ``video_jobs`` row.

    Used both as the ``POST`` response (job submitted) and the ``GET``
    response (current status). When ``status == 'succeeded'`` the
    ``result_url`` is set; when ``status in {failed, refunded}`` the
    ``error_*`` fields are populated.
    """

    job_id: int
    status: _VideoStatus
    tariff: _VideoTariff
    duration_s: int
    prompt: str
    style: str | None
    reference_image_url: str | None
    tokens_cost: int
    result_url: str | None
    error_code: str | None
    error_message: str | None
    provider_job_id: str | None
    transaction_id: int | None
    refund_transaction_id: int | None
    request_id: str
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


def _to_response(view: VideoJobView) -> VideoJobResponse:
    return VideoJobResponse(
        job_id=view.id,
        status=view.status,  # type: ignore[arg-type]
        tariff=view.tariff,  # type: ignore[arg-type]
        duration_s=view.duration_s,
        prompt=view.prompt,
        style=view.style,
        reference_image_url=view.reference_image_url,
        tokens_cost=view.tokens_cost,
        result_url=view.result_url,
        error_code=view.error_code,
        error_message=view.error_message,
        provider_job_id=view.provider_job_id,
        transaction_id=view.transaction_id,
        refund_transaction_id=view.refund_transaction_id,
        request_id=view.request_id,
        created_at=view.created_at,
        updated_at=view.updated_at,
        completed_at=view.completed_at,
    )


# --------------------------------------------------------------- video endpoints


@router.post(
    "/video",
    response_model=VideoJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit an async video generation job; debits tokens by tariff",
    dependencies=[Depends(rate_limit(action="video"))],
)
async def generate_video(
    body: VideoGenerationRequest,
    session: SessionDep,
    composio: ComposioClientDep,
    user: Annotated[User, Depends(get_current_user_from_init_data)],
) -> VideoJobResponse:
    """Submit a video-generation job.

    Tokens are debited up-front; failures during submission refund the
    debit automatically. The response includes the ``job_id`` and the
    initial ``status`` (typically ``queued``). Poll
    ``GET /api/v1/generate/video/{job_id}`` for progress.

    Failure modes:

    * ``400 invalid_prompt`` / ``invalid_tariff`` / ``invalid_reference``
    * ``402 insufficient_tokens`` — balance below the tariff price
    * ``404 user_not_found``
    * ``502 video_provider_error`` — Composio rejected the submission
    """
    service = VideoGenerationService(session, composio)
    request_id = uuid.uuid4().hex

    try:
        view = await service.create(
            user_id=user.id,
            prompt=body.prompt,
            tariff=body.tariff,
            duration_s=body.duration_s,
            style=body.style,
            reference_image_url=body.reference_image_url,
            request_id=request_id,
        )
    except VideoInvalidPromptError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_prompt", "message": str(exc)},
        ) from exc
    except InvalidTariffError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "invalid_tariff",
                "message": str(exc),
                "supported_tariffs": sorted(SUPPORTED_TARIFFS),
                "supported_durations": sorted(DURATION_TO_TARIFF),
                "tariff_cost": dict(TARIFF_COST),
                "tariff_duration_s": dict(TARIFF_DURATION),
            },
        ) from exc
    except InvalidReferenceImageError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_reference", "message": str(exc)},
        ) from exc
    except InsufficientTokensError as exc:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "insufficient_tokens",
                "required": exc.required,
                "available": exc.available,
            },
        ) from exc
    except UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="user_not_found",
        ) from exc
    except VideoProviderError as exc:
        # The service has already refunded the debit and marked the row
        # ``failed``/``refunded`` — commit so the audit trail and refund
        # transaction are persisted, then surface a 502 to the caller.
        try:
            await session.commit()
        except Exception:  # noqa: BLE001 — commit failure is secondary here
            await session.rollback()
        logger.warning(
            "generate.video.provider_error",
            user_id=user.id,
            request_id=request_id,
            error=str(exc),
            provider_error=exc.provider_error,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "video_provider_error",
                "message": str(exc),
                "provider_error": exc.provider_error,
            },
        ) from exc
    except VideoGenerationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_request", "message": str(exc)},
        ) from exc

    try:
        await session.commit()
    except Exception as exc:  # noqa: BLE001 — surface a clean 500
        await session.rollback()
        logger.exception(
            "generate.video.commit_failed",
            user_id=user.id,
            request_id=request_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="commit_failed",
        ) from exc

    return _to_response(view)


@router.get(
    "/video/{job_id}",
    response_model=VideoJobResponse,
    summary="Get the current status of a video job (triggers one poll)",
)
async def get_video_job(
    job_id: int,
    session: SessionDep,
    composio: ComposioClientDep,
    user: Annotated[User, Depends(get_current_user_from_init_data)],
) -> VideoJobResponse:
    """Read the current state of a video job.

    For non-terminal jobs, the service triggers a single inline poll so
    the UI can observe a transition from ``queued`` → ``succeeded``
    without waiting for the background worker.

    Cross-user reads are rejected with ``404``.
    """
    service = VideoGenerationService(session, composio)
    try:
        view = await service.get_and_refresh(job_id, user_id=user.id)
    except VideoJobNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "video_job_not_found", "job_id": job_id},
        ) from exc

    # The inline poll may have written status / refund rows — persist them.
    try:
        await session.commit()
    except Exception as exc:  # noqa: BLE001 — surface a clean 500
        await session.rollback()
        logger.exception(
            "generate.video.status_commit_failed",
            user_id=user.id,
            job_id=job_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="commit_failed",
        ) from exc

    return _to_response(view)


# ---------------------------------------------------------------- text schemas


_TextMode = Literal["basic", "advanced", "autonomous_agent"]


class TextGenerationRequest(BaseModel):
    """Body for ``POST /api/v1/generate/text`` (and the SSE sibling)."""

    prompt: str = Field(..., min_length=1, max_length=MAX_TEXT_PROMPT_LENGTH)
    mode: _TextMode = MODE_BASIC  # type: ignore[assignment]
    system_prompt: str | None = Field(
        default=None,
        max_length=MAX_TEXT_SYSTEM_PROMPT_LENGTH,
        description="Optional system message prepended to the conversation.",
    )
    temperature: float | None = Field(
        default=None,
        ge=0.0,
        le=2.0,
        description="Sampling temperature; defaults to 0.7 when omitted.",
    )
    max_tokens: int | None = Field(
        default=None,
        ge=1,
        le=4096,
        description="Maximum response tokens; defaults to 1024 when omitted.",
    )
    thread_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        description=(
            "Caller-controlled conversation identifier. When set, the "
            "configured history backend (Redis for free, DB for premium) "
            "loads / appends turns around this call."
        ),
    )


class TextGenerationResponse(BaseModel):
    text: str
    mode: _TextMode
    tokens_spent: int
    new_balance: int
    usage_log_id: int
    transaction_id: int
    request_id: str
    composio_tool: str
    mcp_server: str | None = None
    processing_time_ms: int | None = None
    thread_id: str | None = None


def _text_response(
    result: TextGenerationResult, *, request_id: str
) -> TextGenerationResponse:
    return TextGenerationResponse(
        text=result.text,
        mode=result.mode,  # type: ignore[arg-type]
        tokens_spent=result.tokens_spent,
        new_balance=result.new_balance,
        usage_log_id=result.usage_log_id,
        transaction_id=result.transaction_id,
        request_id=request_id,
        composio_tool=result.composio_tool,
        mcp_server=result.mcp_server,
        processing_time_ms=result.processing_time_ms,
        thread_id=result.thread_id,
    )


def _build_text_history(session, user: User) -> ConversationHistory:
    """Pick the conversation-history backend for ``user``.

    Premium users get durable storage in ``chat_threads`` / ``chat_messages``
    so the bot and Mini-App can show their threads across devices;
    free / anonymous users keep their history in Redis with a sliding TTL
    (cheap, ephemeral, capped per thread).
    """
    if user.is_premium:
        return DbConversationHistory(session)
    return RedisConversationHistory(get_redis())


def _build_text_service(session, user: User) -> TextGenerationService:
    composio = get_composio_client()
    history = _build_text_history(session, user)
    return TextGenerationService(session, composio, history=history)


def _raise_text_error(
    exc: Exception,
    *,
    request_id: str,
    user_id: int,
    session_to_rollback,
) -> None:
    """Translate a service-layer error into the right HTTP response.

    Provider errors trigger a rollback first so partial debits / history
    writes from the failed attempt don't leak into the audit trail.
    """
    if isinstance(exc, TextInvalidPromptError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_prompt", "message": str(exc)},
        ) from exc
    if isinstance(exc, InvalidModeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "invalid_mode",
                "message": str(exc),
                "supported": sorted(SUPPORTED_MODES),
                "mode_cost": dict(MODE_COST),
            },
        ) from exc
    if isinstance(exc, InvalidTemperatureError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_temperature", "message": str(exc)},
        ) from exc
    if isinstance(exc, InvalidMaxTokensError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_max_tokens", "message": str(exc)},
        ) from exc
    if isinstance(exc, InsufficientTokensError):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "insufficient_tokens",
                "required": exc.required,
                "available": exc.available,
            },
        ) from exc
    if isinstance(exc, UserNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="user_not_found",
        ) from exc
    if isinstance(exc, TextProviderError):
        # The service hasn't committed anything yet — drop the in-flight
        # state so a retry starts clean.
        # session_to_rollback.rollback is awaited by the caller.
        logger.warning(
            "generate.text.provider_error",
            user_id=user_id,
            request_id=request_id,
            error=str(exc),
            provider_error=exc.provider_error,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "text_provider_error",
                "message": str(exc),
                "provider_error": exc.provider_error,
            },
        ) from exc


# --------------------------------------------------------------- text endpoint


@router.post(
    "/text",
    response_model=TextGenerationResponse,
    summary="Generate text (basic / advanced / autonomous_agent) and debit tokens",
    dependencies=[Depends(rate_limit(action="text"))],
)
async def generate_text(
    body: TextGenerationRequest,
    session: SessionDep,
    user: Annotated[User, Depends(get_current_user_from_init_data)],
) -> TextGenerationResponse:
    """Synchronous text generation via the Composio text toolkits.

    Failure modes:

    * ``400 invalid_prompt`` / ``invalid_mode`` / ``invalid_temperature``
      / ``invalid_max_tokens``
    * ``402 insufficient_tokens`` — balance below the mode price
    * ``404 user_not_found``
    * ``502 text_provider_error`` — Composio call failed or returned empty
    * ``500 commit_failed`` — DB error on commit
    """
    service = _build_text_service(session, user)
    request_id = uuid.uuid4().hex

    try:
        result = await service.generate(
            user_id=user.id,
            prompt=body.prompt,
            mode=body.mode,
            system_prompt=body.system_prompt,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
            thread_id=body.thread_id,
            request_id=request_id,
        )
    except TextProviderError as exc:
        await session.rollback()
        _raise_text_error(
            exc,
            request_id=request_id,
            user_id=user.id,
            session_to_rollback=session,
        )
        raise  # unreachable; satisfies type-checker
    except (
        TextInvalidPromptError,
        InvalidModeError,
        InvalidTemperatureError,
        InvalidMaxTokensError,
        InsufficientTokensError,
        UserNotFoundError,
    ) as exc:
        _raise_text_error(
            exc,
            request_id=request_id,
            user_id=user.id,
            session_to_rollback=session,
        )
        raise  # unreachable

    try:
        await session.commit()
    except Exception as exc:  # noqa: BLE001 — surface a clean 500
        await session.rollback()
        logger.exception(
            "generate.text.commit_failed",
            user_id=user.id,
            request_id=request_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="commit_failed",
        ) from exc

    return _text_response(result, request_id=request_id)


@router.post(
    "/text/stream",
    summary="Stream a text generation response over SSE",
    dependencies=[Depends(rate_limit(action="text"))],
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def generate_text_stream(
    body: TextGenerationRequest,
    session: SessionDep,
    user: Annotated[User, Depends(get_current_user_from_init_data)],
) -> StreamingResponse:
    """Stream a text response as Server-Sent Events.

    The body and validation rules match :func:`generate_text`. The
    response is a stream of ``data: {json}\\n\\n`` frames; the first frame
    carries ``{"event": "start", "request_id": ...}``, subsequent
    ``"delta"`` frames carry incremental text, and a terminal
    ``"final"`` frame carries the same payload as the non-streaming
    endpoint.

    Validation errors are raised before the response starts streaming
    (so callers still see proper 4xx). Once streaming begins, the only
    transport-level error surface is a ``{"event": "error", ...}`` frame
    immediately followed by stream closure.
    """
    service = _build_text_service(session, user)
    request_id = uuid.uuid4().hex

    # Pre-validate by surfacing the most common errors before we open the
    # SSE response — the client gets a normal JSON 4xx instead of a half
    # stream that ends with an "error" frame.
    try:
        stream = await service.iter_generate(
            user_id=user.id,
            prompt=body.prompt,
            mode=body.mode,
            system_prompt=body.system_prompt,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
            thread_id=body.thread_id,
            request_id=request_id,
        )
    except TextProviderError as exc:
        await session.rollback()
        _raise_text_error(
            exc,
            request_id=request_id,
            user_id=user.id,
            session_to_rollback=session,
        )
        raise  # unreachable
    except (
        TextInvalidPromptError,
        InvalidModeError,
        InvalidTemperatureError,
        InvalidMaxTokensError,
        InsufficientTokensError,
        UserNotFoundError,
    ) as exc:
        _raise_text_error(
            exc,
            request_id=request_id,
            user_id=user.id,
            session_to_rollback=session,
        )
        raise  # unreachable

    # ``iter_generate`` runs the full pipeline synchronously and only
    # *then* hands us a chunk iterator — so by the time we reach this
    # point, tokens have been debited and history persisted. Commit the
    # accumulated session state now so a slow consumer can't keep the
    # transaction open across the entire stream.
    try:
        await session.commit()
    except Exception as exc:  # noqa: BLE001 — surface a clean 500
        await session.rollback()
        logger.exception(
            "generate.text.stream_commit_failed",
            user_id=user.id,
            request_id=request_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="commit_failed",
        ) from exc

    async def _sse() -> AsyncIterator[bytes]:
        yield _sse_frame({"event": "start", "request_id": request_id})
        try:
            async for chunk in stream:
                if chunk.kind == "delta":
                    yield _sse_frame(
                        {"event": "delta", "content": chunk.content}
                    )
                elif chunk.kind == "final" and chunk.result is not None:
                    payload = _text_response(
                        chunk.result, request_id=request_id
                    ).model_dump()
                    payload["event"] = "final"
                    yield _sse_frame(payload)
        except Exception as exc:  # noqa: BLE001 — never leak through SSE
            logger.exception(
                "generate.text.stream_failed",
                user_id=user.id,
                request_id=request_id,
                error=str(exc),
            )
            yield _sse_frame(
                {
                    "event": "error",
                    "error": "stream_failed",
                    "message": str(exc),
                }
            )
        yield _sse_frame({"event": "done"})

    return StreamingResponse(
        _sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "X-Request-Id": request_id,
        },
    )


def _sse_frame(payload: dict) -> bytes:
    """Encode ``payload`` as a single SSE ``data:`` frame."""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()


# --------------------------------------------------------------- search schemas


class WebSearchRequest(BaseModel):
    """Body for ``POST /api/v1/generate/search``."""

    query: str = Field(..., min_length=1, max_length=MAX_QUERY_LENGTH)
    max_results: int | None = Field(
        default=None,
        ge=MIN_MAX_RESULTS,
        le=MAX_MAX_RESULTS,
        description=(
            f"Number of results to return ({MIN_MAX_RESULTS}..{MAX_MAX_RESULTS}); "
            "defaults to 5 when omitted."
        ),
    )


class SearchResultItem(BaseModel):
    title: str
    url: str
    snippet: str | None = None
    source: str | None = None


class WebSearchResponse(BaseModel):
    query: str
    results: list[SearchResultItem]
    summary: str | None = None
    tokens_spent: int
    new_balance: int
    usage_log_id: int
    transaction_id: int
    request_id: str
    composio_tool: str
    mcp_server: str | None = None
    processing_time_ms: int | None = None


# --------------------------------------------------------------- search endpoint


@router.post(
    "/search",
    response_model=WebSearchResponse,
    summary="Run a web search via the Composio search toolkit (3 tokens)",
    dependencies=[Depends(rate_limit(action="search"))],
)
async def generate_search(
    body: WebSearchRequest,
    session: SessionDep,
    composio: ComposioClientDep,
    user: Annotated[User, Depends(get_current_user_from_init_data)],
) -> WebSearchResponse:
    """Synchronous web search via the Composio search toolkit.

    Failure modes:

    * ``400 invalid_query`` / ``invalid_max_results``
    * ``402 insufficient_tokens`` — balance below the search price
    * ``404 user_not_found``
    * ``502 search_provider_error`` — Composio call failed / no results
    * ``500 commit_failed`` — DB error on commit
    """
    service = WebSearchService(session, composio)
    request_id = uuid.uuid4().hex

    try:
        outcome = await service.search(
            user_id=user.id,
            query=body.query,
            max_results=body.max_results,
            request_id=request_id,
        )
    except SearchInvalidQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_query", "message": str(exc)},
        ) from exc
    except InvalidMaxResultsError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "invalid_max_results",
                "message": str(exc),
                "min": MIN_MAX_RESULTS,
                "max": MAX_MAX_RESULTS,
            },
        ) from exc
    except InsufficientTokensError as exc:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "insufficient_tokens",
                "required": exc.required,
                "available": exc.available,
                "cost": SEARCH_COST,
            },
        ) from exc
    except UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="user_not_found",
        ) from exc
    except SearchProviderError as exc:
        await session.rollback()
        logger.warning(
            "generate.search.provider_error",
            user_id=user.id,
            request_id=request_id,
            error=str(exc),
            provider_error=exc.provider_error,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "search_provider_error",
                "message": str(exc),
                "provider_error": exc.provider_error,
            },
        ) from exc

    try:
        await session.commit()
    except Exception as exc:  # noqa: BLE001 — surface a clean 500
        await session.rollback()
        logger.exception(
            "generate.search.commit_failed",
            user_id=user.id,
            request_id=request_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="commit_failed",
        ) from exc

    return WebSearchResponse(
        query=outcome.query,
        results=[
            SearchResultItem(
                title=r.title,
                url=r.url,
                snippet=r.snippet,
                source=r.source,
            )
            for r in outcome.results
        ],
        summary=outcome.summary,
        tokens_spent=outcome.tokens_spent,
        new_balance=outcome.new_balance,
        usage_log_id=outcome.usage_log_id,
        transaction_id=outcome.transaction_id,
        request_id=request_id,
        composio_tool=outcome.composio_tool,
        mcp_server=outcome.mcp_server,
        processing_time_ms=outcome.processing_time_ms,
    )


# ---------------------------------------------------------------- voice schemas


class VoiceProcessingRequest(BaseModel):
    """Body for ``POST /api/v1/generate/voice``.

    Either ``audio_url`` or ``audio_base64`` must be supplied. When
    ``synthesize_reply`` is on the server runs an additional TTS pass for
    ``reply_prompt`` (or the transcript itself if no prompt was given).
    """

    audio_url: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_AUDIO_URL_LENGTH,
        description="Absolute http(s) URL to the voice file to transcribe.",
    )
    audio_base64: str | None = Field(
        default=None,
        min_length=1,
        description="Base64-encoded audio payload (≤25 MB after decoding).",
    )
    language: str | None = Field(
        default=None,
        max_length=MAX_LANGUAGE_LENGTH,
        description="Optional BCP-47 language hint for the STT engine.",
    )
    duration_seconds: float | None = Field(
        default=None,
        ge=0.0,
        description=(
            "Optional client-side hint about the audio duration; the "
            "service enforces an upper bound of 5 minutes."
        ),
    )
    synthesize_reply: bool = Field(
        default=False,
        description=(
            "When True the server also runs TTS and returns "
            "``reply_audio_url``."
        ),
    )
    reply_prompt: str | None = Field(
        default=None,
        max_length=MAX_VOICE_PROMPT_LENGTH,
        description=(
            "Optional text to synthesise instead of the transcript. "
            "Requires synthesize_reply=True."
        ),
    )
    voice: str | None = Field(
        default=None,
        max_length=MAX_VOICE_LENGTH,
        description="Optional TTS voice identifier (provider-specific).",
    )

    @model_validator(mode="after")
    def _require_audio_reference(self) -> VoiceProcessingRequest:
        if not self.audio_url and not self.audio_base64:
            # Surface the missing-input case as a 422 from Pydantic rather
            # than letting it propagate as a 400 from the service layer.
            raise ValueError("audio_url or audio_base64 is required")
        return self


class VoiceProcessingResponse(BaseModel):
    transcript: str
    language: str | None = None
    reply_text: str | None = None
    reply_audio_url: str | None = None
    duration_seconds: float | None = None
    tokens_spent: int
    new_balance: int
    usage_log_id: int
    transaction_id: int
    request_id: str
    composio_tool: str
    mcp_server: str | None = None
    processing_time_ms: int | None = None


# --------------------------------------------------------------- voice endpoint


@router.post(
    "/voice",
    response_model=VoiceProcessingResponse,
    summary="Transcribe a voice message (optionally synthesise reply, 5 tokens)",
    dependencies=[Depends(rate_limit(action="voice"))],
)
async def generate_voice(
    body: VoiceProcessingRequest,
    session: SessionDep,
    composio: ComposioClientDep,
    user: Annotated[User, Depends(get_current_user_from_init_data)],
) -> VoiceProcessingResponse:
    """Synchronous voice processing via the Composio voice toolkit.

    The flat 5-token cost covers STT plus an optional TTS pass when
    ``synthesize_reply`` is set.

    Failure modes:

    * ``400 invalid_audio`` / ``invalid_reply_prompt``
    * ``402 insufficient_tokens`` — balance below the voice price
    * ``404 user_not_found``
    * ``502 voice_provider_error`` — Composio call failed / no transcript
    * ``500 commit_failed`` — DB error on commit
    """
    service = VoiceProcessingService(session, composio)
    request_id = uuid.uuid4().hex

    try:
        outcome = await service.process(
            user_id=user.id,
            audio_url=body.audio_url,
            audio_base64=body.audio_base64,
            language=body.language,
            synthesize_reply=body.synthesize_reply,
            reply_prompt=body.reply_prompt,
            voice=body.voice,
            duration_seconds=body.duration_seconds,
            request_id=request_id,
        )
    except InvalidAudioError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_audio", "message": str(exc)},
        ) from exc
    except InvalidVoicePromptError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_reply_prompt", "message": str(exc)},
        ) from exc
    except InsufficientTokensError as exc:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "insufficient_tokens",
                "required": exc.required,
                "available": exc.available,
                "cost": VOICE_COST,
            },
        ) from exc
    except UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="user_not_found",
        ) from exc
    except VoiceProviderError as exc:
        await session.rollback()
        logger.warning(
            "generate.voice.provider_error",
            user_id=user.id,
            request_id=request_id,
            error=str(exc),
            provider_error=exc.provider_error,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "voice_provider_error",
                "message": str(exc),
                "provider_error": exc.provider_error,
            },
        ) from exc

    try:
        await session.commit()
    except Exception as exc:  # noqa: BLE001 — surface a clean 500
        await session.rollback()
        logger.exception(
            "generate.voice.commit_failed",
            user_id=user.id,
            request_id=request_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="commit_failed",
        ) from exc

    return VoiceProcessingResponse(
        transcript=outcome.transcript,
        language=outcome.language,
        reply_text=outcome.reply_text,
        reply_audio_url=outcome.reply_audio_url,
        duration_seconds=outcome.duration_seconds,
        tokens_spent=outcome.tokens_spent,
        new_balance=outcome.new_balance,
        usage_log_id=outcome.usage_log_id,
        transaction_id=outcome.transaction_id,
        request_id=request_id,
        composio_tool=outcome.composio_tool,
        mcp_server=outcome.mcp_server,
        processing_time_ms=outcome.processing_time_ms,
    )


# ------------------------------------------------------------ document schemas


_DocumentFormat = Literal["pdf", "docx", "txt"]


class DocumentAnalysisRequest(BaseModel):
    """Body for ``POST /api/v1/generate/document``.

    Either ``document_url`` or ``document_base64`` must be supplied. The
    file format can be passed explicitly or inferred from ``filename`` /
    the trailing extension of ``document_url``.
    """

    document_url: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_DOCUMENT_URL_LENGTH,
        description="Absolute http(s) URL to the document to parse.",
    )
    document_base64: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "Base64-encoded document payload (≤10 MB free / ≤50 MB premium)."
        ),
    )
    format: _DocumentFormat | None = Field(
        default=None,
        description="Explicit document format; inferred from URL/filename when omitted.",
    )
    filename: str | None = Field(
        default=None,
        max_length=MAX_FILENAME_LENGTH,
        description="Optional original filename — used for format inference.",
    )
    file_size_bytes: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Optional client-supplied size used to enforce the per-tier cap "
            "before the file is downloaded by the provider."
        ),
    )
    question: str | None = Field(
        default=None,
        max_length=MAX_QUESTION_LENGTH,
        description="Optional Q&A prompt run against the parsed document.",
    )

    @model_validator(mode="after")
    def _require_document_reference(self) -> DocumentAnalysisRequest:
        if not self.document_url and not self.document_base64:
            raise ValueError("document_url or document_base64 is required")
        return self


class DocumentAnalysisResponse(BaseModel):
    format: _DocumentFormat
    text: str
    summary: str | None = None
    answer: str | None = None
    question: str | None = None
    page_count: int | None = None
    char_count: int
    file_size_bytes: int | None = None
    tokens_spent: int
    new_balance: int
    usage_log_id: int
    transaction_id: int
    request_id: str
    composio_tool: str
    mcp_server: str | None = None
    processing_time_ms: int | None = None


# ----------------------------------------------------------- document endpoint


@router.post(
    "/document",
    response_model=DocumentAnalysisResponse,
    summary="Analyse a document (PDF/DOCX/TXT) and debit 20 tokens",
    dependencies=[Depends(rate_limit(action="document"))],
)
async def generate_document(
    body: DocumentAnalysisRequest,
    session: SessionDep,
    composio: ComposioClientDep,
    user: Annotated[User, Depends(get_current_user_from_init_data)],
) -> DocumentAnalysisResponse:
    """Synchronous document analysis via the Composio document toolkit.

    Premium users get a 50 MB upload cap; free users 10 MB. The flat
    20-token cost covers extraction + summary, plus optional Q&A when
    ``question`` is provided.

    Failure modes:

    * ``400 invalid_document`` / ``invalid_format`` / ``invalid_question``
    * ``402 insufficient_tokens`` — balance below the document price
    * ``404 user_not_found``
    * ``413 document_too_large`` — payload over the per-tier cap
    * ``502 document_provider_error`` — Composio call failed / empty result
    * ``500 commit_failed`` — DB error on commit
    """
    service = DocumentAnalysisService(session, composio)
    request_id = uuid.uuid4().hex

    try:
        outcome = await service.analyze(
            user_id=user.id,
            document_url=body.document_url,
            document_base64=body.document_base64,
            format=body.format,
            filename=body.filename,
            file_size_bytes=body.file_size_bytes,
            question=body.question,
            is_premium=user.is_premium,
            request_id=request_id,
        )
    except InvalidDocumentFormatError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "invalid_format",
                "message": str(exc),
                "supported": sorted(SUPPORTED_FORMATS),
            },
        ) from exc
    except InvalidDocumentError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_document", "message": str(exc)},
        ) from exc
    except InvalidQuestionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_question", "message": str(exc)},
        ) from exc
    except DocumentTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "error": "document_too_large",
                "message": str(exc),
                "size": exc.size,
                "limit": exc.limit,
                "is_premium": exc.is_premium,
                "limit_free": MAX_FILE_BYTES_FREE,
                "limit_premium": MAX_FILE_BYTES_PREMIUM,
            },
        ) from exc
    except InsufficientTokensError as exc:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "insufficient_tokens",
                "required": exc.required,
                "available": exc.available,
                "cost": DOCUMENT_COST,
            },
        ) from exc
    except UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="user_not_found",
        ) from exc
    except DocumentProviderError as exc:
        await session.rollback()
        logger.warning(
            "generate.document.provider_error",
            user_id=user.id,
            request_id=request_id,
            error=str(exc),
            provider_error=exc.provider_error,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "document_provider_error",
                "message": str(exc),
                "provider_error": exc.provider_error,
            },
        ) from exc

    try:
        await session.commit()
    except Exception as exc:  # noqa: BLE001 — surface a clean 500
        await session.rollback()
        logger.exception(
            "generate.document.commit_failed",
            user_id=user.id,
            request_id=request_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="commit_failed",
        ) from exc

    return DocumentAnalysisResponse(
        format=outcome.format,  # type: ignore[arg-type]
        text=outcome.text,
        summary=outcome.summary,
        answer=outcome.answer,
        question=outcome.question,
        page_count=outcome.page_count,
        char_count=outcome.char_count,
        file_size_bytes=outcome.file_size_bytes,
        tokens_spent=outcome.tokens_spent,
        new_balance=outcome.new_balance,
        usage_log_id=outcome.usage_log_id,
        transaction_id=outcome.transaction_id,
        request_id=request_id,
        composio_tool=outcome.composio_tool,
        mcp_server=outcome.mcp_server,
        processing_time_ms=outcome.processing_time_ms,
    )
