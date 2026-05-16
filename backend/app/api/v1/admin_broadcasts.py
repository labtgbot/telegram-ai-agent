"""Admin Broadcast Messaging endpoints (Phase 3, issue #28).

Endpoints under ``/admin/broadcasts``:

* ``POST /admin/broadcasts`` — compose a new broadcast (immediate or
  scheduled).  Requires ``support_admin`` or higher.
* ``POST /admin/broadcasts/preview-audience`` — count the audience for a
  given selector before pushing the send button.  ``analyst`` and up.
* ``GET  /admin/broadcasts`` — paginated list of campaigns.  ``analyst``.
* ``GET  /admin/broadcasts/{id}`` — single campaign metadata.  ``analyst``.
* ``GET  /admin/broadcasts/{id}/stats`` — delivery counter breakdown
  driven by ``broadcast_recipients`` aggregations.  ``analyst``.
* ``POST /admin/broadcasts/{id}/cancel`` — stop a draft / scheduled /
  in-progress campaign.  ``support_admin`` and up.

Every mutating endpoint writes an :class:`AdminAuditLog` row through the
service layer in the same transaction.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    status,
)
from pydantic import BaseModel, Field

from app.auth.dependencies import SessionDep, get_current_admin
from app.auth.rbac import Role, require_role
from app.core.logging import get_logger
from app.models.broadcast import (
    BROADCAST_AUDIENCES,
    Broadcast,
)
from app.models.user import User
from app.services.broadcast import (
    MAX_BUTTONS,
    MAX_TEXT_LEN,
    MAX_TITLE_LEN,
    BroadcastButton,
    BroadcastDraft,
    BroadcastNotCancellableError,
    BroadcastNotFoundError,
    EmptyAudienceError,
    InvalidAudienceError,
    InvalidBroadcastPayloadError,
    cancel_broadcast,
    create_broadcast,
    get_broadcast,
    get_broadcast_stats,
    list_broadcasts,
    preview_audience,
)

router = APIRouter(prefix="/admin", tags=["admin-broadcasts"])
logger = get_logger(__name__)


# ---------------------------------------------------------------- request models


class BroadcastButtonPayload(BaseModel):
    text: str = Field(..., min_length=1, max_length=64)
    url: str | None = Field(default=None, max_length=2048)
    callback_data: str | None = Field(default=None, max_length=64)


class BroadcastCreateRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_TEXT_LEN)
    title: str | None = Field(default=None, max_length=MAX_TITLE_LEN)
    parse_mode: str | None = Field(default="HTML", max_length=16)
    media_type: str | None = Field(default=None, max_length=16)
    media_url: str | None = Field(default=None, max_length=2048)
    buttons: list[BroadcastButtonPayload] = Field(default_factory=list, max_length=MAX_BUTTONS)
    audience: str = Field(..., max_length=32)
    audience_filter: dict[str, Any] | None = None
    scheduled_at: datetime | None = None


class PreviewAudienceRequest(BaseModel):
    audience: str = Field(..., max_length=32)
    audience_filter: dict[str, Any] | None = None


# ---------------------------------------------------------------- response models


class PreviewAudienceResponse(BaseModel):
    audience: str
    total: int


class BroadcastResponse(BaseModel):
    id: int
    created_by: int
    title: str | None = None
    text: str
    parse_mode: str | None = None
    media_type: str | None = None
    media_url: str | None = None
    buttons: list[dict[str, Any]] | None = None
    audience: str
    audience_filter: dict[str, Any] | None = None
    status: str
    scheduled_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    cancelled_at: datetime | None = None
    total_recipients: int
    sent_count: int
    delivered_count: int
    failed_count: int
    skipped_count: int
    clicks_count: int
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, broadcast: Broadcast) -> BroadcastResponse:
        return cls(
            id=broadcast.id,
            created_by=broadcast.created_by,
            title=broadcast.title,
            text=broadcast.text,
            parse_mode=broadcast.parse_mode,
            media_type=broadcast.media_type,
            media_url=broadcast.media_url,
            buttons=broadcast.buttons,
            audience=broadcast.audience,
            audience_filter=broadcast.audience_filter,
            status=broadcast.status,
            scheduled_at=broadcast.scheduled_at,
            started_at=broadcast.started_at,
            finished_at=broadcast.finished_at,
            cancelled_at=broadcast.cancelled_at,
            total_recipients=int(broadcast.total_recipients or 0),
            sent_count=int(broadcast.sent_count or 0),
            delivered_count=int(broadcast.delivered_count or 0),
            failed_count=int(broadcast.failed_count or 0),
            skipped_count=int(broadcast.skipped_count or 0),
            clicks_count=int(broadcast.clicks_count or 0),
            last_error=broadcast.last_error,
            created_at=broadcast.created_at,
            updated_at=broadcast.updated_at,
        )


class BroadcastListResponse(BaseModel):
    items: list[BroadcastResponse]
    total: int
    page: int
    limit: int
    has_more: bool


class BroadcastStatsResponse(BaseModel):
    broadcast: BroadcastResponse
    total_recipients: int
    pending: int
    sent: int
    delivered: int
    failed: int
    skipped: int
    clicks: int


# ---------------------------------------------------------------- helpers


def _request_meta(request: Request) -> tuple[str | None, str | None]:
    ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (
        request.client.host if request.client else None
    )
    return ip or None, request.headers.get("user-agent")


async def _commit_or_500(session: Any) -> None:
    try:
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        logger.exception("admin_broadcasts.commit_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="commit_failed",
        ) from exc


def _draft_from_request(payload: BroadcastCreateRequest) -> BroadcastDraft:
    buttons = tuple(
        BroadcastButton(
            text=b.text,
            url=b.url,
            callback_data=b.callback_data,
        )
        for b in payload.buttons
    )
    return BroadcastDraft(
        text=payload.text,
        title=payload.title,
        parse_mode=payload.parse_mode,
        media_type=payload.media_type,
        media_url=payload.media_url,
        buttons=buttons,
        audience=payload.audience,
        audience_filter=payload.audience_filter,
        scheduled_at=payload.scheduled_at,
    )


# ---------------------------------------------------------------- endpoints


@router.post(
    "/broadcasts/preview-audience",
    response_model=PreviewAudienceResponse,
    summary="Count users that match a given audience selector",
)
async def preview_audience_endpoint(
    payload: PreviewAudienceRequest,
    session: SessionDep,
    admin: Annotated[User, Depends(get_current_admin)],
) -> PreviewAudienceResponse:
    try:
        total = await preview_audience(
            session,
            audience=payload.audience,
            audience_filter=payload.audience_filter,
        )
    except InvalidAudienceError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return PreviewAudienceResponse(audience=payload.audience, total=total)


@router.post(
    "/broadcasts",
    response_model=BroadcastResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a broadcast (optionally scheduled for later)",
)
async def create_broadcast_endpoint(
    payload: BroadcastCreateRequest,
    request: Request,
    session: SessionDep,
    admin: Annotated[User, Depends(require_role(Role.SUPPORT_ADMIN))],
) -> BroadcastResponse:
    ip, ua = _request_meta(request)
    draft = _draft_from_request(payload)
    try:
        broadcast = await create_broadcast(
            session,
            admin=admin,
            draft=draft,
            ip_address=ip,
            user_agent=ua,
        )
    except (InvalidAudienceError, InvalidBroadcastPayloadError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except EmptyAudienceError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="empty_audience",
        ) from exc

    await _commit_or_500(session)
    return BroadcastResponse.from_model(broadcast)


@router.get(
    "/broadcasts",
    response_model=BroadcastListResponse,
    summary="List broadcasts (newest first)",
)
async def list_broadcasts_endpoint(
    session: SessionDep,
    admin: Annotated[User, Depends(get_current_admin)],
    status_filter: Annotated[str | None, Query(alias="status", max_length=32)] = None,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
) -> BroadcastListResponse:
    result = await list_broadcasts(session, status=status_filter, page=page, limit=limit)
    return BroadcastListResponse(
        items=[BroadcastResponse.from_model(b) for b in result.items],
        total=result.total,
        page=result.page,
        limit=result.limit,
        has_more=result.has_more,
    )


@router.get(
    "/broadcasts/audiences",
    summary="List supported audience selectors",
)
async def list_audiences_endpoint(
    admin: Annotated[User, Depends(get_current_admin)],
) -> dict[str, list[str]]:
    return {"audiences": list(BROADCAST_AUDIENCES)}


@router.get(
    "/broadcasts/{broadcast_id}",
    response_model=BroadcastResponse,
    summary="Fetch a single broadcast by id",
)
async def get_broadcast_endpoint(
    broadcast_id: int,
    session: SessionDep,
    admin: Annotated[User, Depends(get_current_admin)],
) -> BroadcastResponse:
    try:
        broadcast = await get_broadcast(session, broadcast_id)
    except BroadcastNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="broadcast_not_found",
        ) from exc
    return BroadcastResponse.from_model(broadcast)


@router.get(
    "/broadcasts/{broadcast_id}/stats",
    response_model=BroadcastStatsResponse,
    summary="Delivery stats for a broadcast",
)
async def get_broadcast_stats_endpoint(
    broadcast_id: int,
    session: SessionDep,
    admin: Annotated[User, Depends(get_current_admin)],
) -> BroadcastStatsResponse:
    try:
        stats = await get_broadcast_stats(session, broadcast_id)
    except BroadcastNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="broadcast_not_found",
        ) from exc

    return BroadcastStatsResponse(
        broadcast=BroadcastResponse.from_model(stats.broadcast),
        total_recipients=stats.total_recipients,
        pending=stats.pending,
        sent=stats.sent,
        delivered=stats.delivered,
        failed=stats.failed,
        skipped=stats.skipped,
        clicks=stats.clicks,
    )


@router.post(
    "/broadcasts/{broadcast_id}/cancel",
    response_model=BroadcastResponse,
    summary="Cancel a draft / scheduled / in-progress broadcast",
)
async def cancel_broadcast_endpoint(
    broadcast_id: int,
    request: Request,
    session: SessionDep,
    admin: Annotated[User, Depends(require_role(Role.SUPPORT_ADMIN))],
) -> BroadcastResponse:
    ip, ua = _request_meta(request)
    try:
        broadcast = await cancel_broadcast(
            session,
            admin=admin,
            broadcast_id=broadcast_id,
            ip_address=ip,
            user_agent=ua,
        )
    except BroadcastNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="broadcast_not_found",
        ) from exc
    except BroadcastNotCancellableError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    await _commit_or_500(session)
    return BroadcastResponse.from_model(broadcast)


__all__ = [
    "router",
    "BroadcastCreateRequest",
    "BroadcastResponse",
    "BroadcastListResponse",
    "BroadcastStatsResponse",
    "PreviewAudienceRequest",
    "PreviewAudienceResponse",
]
