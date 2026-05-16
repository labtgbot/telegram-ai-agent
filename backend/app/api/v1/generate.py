"""AI generation endpoints.

* ``POST /api/v1/generate/image`` — synchronously generate an image via
  the Composio image toolkit and debit tokens by quality tier.
* ``POST /api/v1/generate/video`` — submit an asynchronous video job
  (provider returns a job id immediately) and debit tokens by tariff.
* ``GET  /api/v1/generate/video/{job_id}`` — poll a video job's status
  (returns the final URL when ready, refund details on failure).

The endpoints require a valid ``X-Telegram-Init-Data`` header (Mini-App
flow) and are rate-limited via the ``image`` / ``video`` quota buckets
defined in ``app.services.rate_limit_config``.

Token cost / quality tiers (mirrors ``ImageGenerationService``):

* ``standard``   →  30 tokens
* ``hd``         →  50 tokens
* ``ultra_hd``   → 100 tokens

Video tariffs (mirrors ``VideoGenerationService``):

* ``short_5s``    →  5s →  100 tokens
* ``medium_15s``  → 15s →  250 tokens
* ``long_60s``    → 60s →  800 tokens
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator

from app.api.rate_limit import rate_limit
from app.auth.dependencies import SessionDep, get_current_user_from_init_data
from app.core.logging import get_logger
from app.models.user import User
from app.services.composio import (
    ComposioClient,
    build_client,
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
