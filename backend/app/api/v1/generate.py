"""AI generation endpoints.

* ``POST /api/v1/generate/image`` — synchronously generate an image via
  the Composio image toolkit and debit tokens by quality tier.

The endpoint requires a valid ``X-Telegram-Init-Data`` header (Mini-App
flow) and is rate-limited via the ``image`` quota bucket defined in
``app.services.rate_limit_config``.

Token cost / quality tiers (mirrors ``ImageGenerationService``):

* ``standard``   →  30 tokens
* ``hd``         →  50 tokens
* ``ultra_hd``   → 100 tokens
"""
from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

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
