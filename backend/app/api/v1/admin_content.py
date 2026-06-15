"""Admin content management endpoints (Phase 3, issue #29).

Endpoints under ``/admin/content``:

* ``GET    /admin/content/prompt-templates``
* ``POST   /admin/content/prompt-templates``
* ``GET    /admin/content/prompt-templates/{id}``
* ``PUT    /admin/content/prompt-templates/{id}``
* ``DELETE /admin/content/prompt-templates/{id}``
* ``GET    /admin/content/faqs``
* ``POST   /admin/content/faqs``
* ``GET    /admin/content/faqs/{id}``
* ``PUT    /admin/content/faqs/{id}``
* ``DELETE /admin/content/faqs/{id}``
* ``GET    /admin/content/welcomes``
* ``POST   /admin/content/welcomes``
* ``GET    /admin/content/welcomes/{id}``
* ``PUT    /admin/content/welcomes/{id}``
* ``DELETE /admin/content/welcomes/{id}``
* ``GET    /admin/content/history`` — combined change history.

Reads and mutations require ``support_admin`` and above, matching the admin
dashboard ``/content`` page gate.  Every mutating endpoint writes an
:class:`AdminAuditLog` row through the service layer in the same
transaction.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    status,
)
from pydantic import BaseModel, Field

from app.auth.admin_access import ADMIN_CONTENT_MIN_ROLE
from app.auth.dependencies import SessionDep
from app.auth.rbac import require_role
from app.core.client_ip import resolve_client_ip
from app.core.logging import get_logger
from app.models.admin_audit_log import AdminAuditLog
from app.models.faq_item import FaqItem
from app.models.prompt_template import PromptTemplate
from app.models.user import User
from app.models.welcome_message import WelcomeMessage
from app.services.admin_content import (
    ContentNotFoundError,
    DuplicateContentCodeError,
    FaqItemDraft,
    InvalidContentPayloadError,
    PromptTemplateDraft,
    WelcomeMessageDraft,
    create_faq_item,
    create_prompt_template,
    create_welcome_message,
    delete_faq_item,
    delete_prompt_template,
    delete_welcome_message,
    get_faq_item,
    get_prompt_template,
    get_welcome_message,
    list_content_history,
    list_faq_items,
    list_prompt_templates,
    list_welcome_messages,
    update_faq_item,
    update_prompt_template,
    update_welcome_message,
)

router = APIRouter(prefix="/admin/content", tags=["admin-content"])
logger = get_logger(__name__)


# ----------------------------------------------------------------- helpers


def _request_meta(request: Request) -> tuple[str | None, str | None]:
    return resolve_client_ip(request), request.headers.get("user-agent")


async def _commit_or_500(session: Any) -> None:
    try:
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        logger.exception("admin_content.commit_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="commit_failed",
        ) from exc


def _payload_error(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=str(exc),
    )


# =========================================================== prompt templates


class PromptTemplatePayload(BaseModel):
    code: str = Field(..., min_length=1, max_length=64)
    title: str = Field(..., min_length=1, max_length=255)
    body: str = Field(..., min_length=1, max_length=8000)
    category: str | None = Field(default=None, max_length=64)
    locale: str = Field(default="en", min_length=1, max_length=8)
    sort_order: int = Field(default=0, ge=0)
    is_active: bool = True


class PromptTemplateResponse(BaseModel):
    id: int
    code: str
    title: str
    body: str
    category: str | None
    locale: str
    sort_order: int
    is_active: bool
    created_by: int | None
    updated_by: int | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, row: PromptTemplate) -> PromptTemplateResponse:
        return cls(
            id=row.id,
            code=row.code,
            title=row.title,
            body=row.body,
            category=row.category,
            locale=row.locale,
            sort_order=int(row.sort_order or 0),
            is_active=bool(row.is_active),
            created_by=row.created_by,
            updated_by=row.updated_by,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


class PromptTemplateListResponse(BaseModel):
    items: list[PromptTemplateResponse]
    total: int
    page: int
    limit: int
    has_more: bool


@router.get(
    "/prompt-templates",
    response_model=PromptTemplateListResponse,
    summary="List prompt templates",
)
async def list_prompt_templates_endpoint(
    session: SessionDep,
    admin: Annotated[User, Depends(require_role(ADMIN_CONTENT_MIN_ROLE))],
    search: Annotated[str | None, Query(max_length=128)] = None,
    category: Annotated[str | None, Query(max_length=64)] = None,
    locale: Annotated[str | None, Query(max_length=8)] = None,
    is_active: Annotated[bool | None, Query()] = None,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
) -> PromptTemplateListResponse:
    result = await list_prompt_templates(
        session,
        search=search,
        category=category,
        locale=locale,
        is_active=is_active,
        page=page,
        limit=limit,
    )
    return PromptTemplateListResponse(
        items=[PromptTemplateResponse.from_model(r) for r in result.items],
        total=result.total,
        page=result.page,
        limit=result.limit,
        has_more=result.has_more,
    )


@router.post(
    "/prompt-templates",
    response_model=PromptTemplateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a prompt template",
)
async def create_prompt_template_endpoint(
    payload: PromptTemplatePayload,
    request: Request,
    session: SessionDep,
    admin: Annotated[User, Depends(require_role(ADMIN_CONTENT_MIN_ROLE))],
) -> PromptTemplateResponse:
    ip, ua = _request_meta(request)
    draft = PromptTemplateDraft(**payload.model_dump())
    try:
        row = await create_prompt_template(
            session, admin=admin, draft=draft, ip_address=ip, user_agent=ua
        )
    except InvalidContentPayloadError as exc:
        raise _payload_error(exc) from exc
    except DuplicateContentCodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="duplicate_code",
        ) from exc
    await _commit_or_500(session)
    return PromptTemplateResponse.from_model(row)


@router.get(
    "/prompt-templates/{template_id}",
    response_model=PromptTemplateResponse,
    summary="Fetch a prompt template",
)
async def get_prompt_template_endpoint(
    template_id: int,
    session: SessionDep,
    admin: Annotated[User, Depends(require_role(ADMIN_CONTENT_MIN_ROLE))],
) -> PromptTemplateResponse:
    try:
        row = await get_prompt_template(session, template_id)
    except ContentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="prompt_template_not_found",
        ) from exc
    return PromptTemplateResponse.from_model(row)


@router.put(
    "/prompt-templates/{template_id}",
    response_model=PromptTemplateResponse,
    summary="Update a prompt template",
)
async def update_prompt_template_endpoint(
    template_id: int,
    payload: PromptTemplatePayload,
    request: Request,
    session: SessionDep,
    admin: Annotated[User, Depends(require_role(ADMIN_CONTENT_MIN_ROLE))],
) -> PromptTemplateResponse:
    ip, ua = _request_meta(request)
    draft = PromptTemplateDraft(**payload.model_dump())
    try:
        row = await update_prompt_template(
            session,
            admin=admin,
            template_id=template_id,
            draft=draft,
            ip_address=ip,
            user_agent=ua,
        )
    except ContentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="prompt_template_not_found",
        ) from exc
    except InvalidContentPayloadError as exc:
        raise _payload_error(exc) from exc
    except DuplicateContentCodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="duplicate_code",
        ) from exc
    await _commit_or_500(session)
    return PromptTemplateResponse.from_model(row)


@router.delete(
    "/prompt-templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a prompt template",
)
async def delete_prompt_template_endpoint(
    template_id: int,
    request: Request,
    session: SessionDep,
    admin: Annotated[User, Depends(require_role(ADMIN_CONTENT_MIN_ROLE))],
) -> None:
    ip, ua = _request_meta(request)
    try:
        await delete_prompt_template(
            session,
            admin=admin,
            template_id=template_id,
            ip_address=ip,
            user_agent=ua,
        )
    except ContentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="prompt_template_not_found",
        ) from exc
    await _commit_or_500(session)
    return None


# ================================================================ FAQ items


class FaqItemPayload(BaseModel):
    question: str = Field(..., min_length=1, max_length=512)
    answer: str = Field(..., min_length=1, max_length=8000)
    category: str | None = Field(default=None, max_length=64)
    locale: str = Field(default="en", min_length=1, max_length=8)
    sort_order: int = Field(default=0, ge=0)
    is_active: bool = True


class FaqItemResponse(BaseModel):
    id: int
    question: str
    answer: str
    category: str | None
    locale: str
    sort_order: int
    is_active: bool
    created_by: int | None
    updated_by: int | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, row: FaqItem) -> FaqItemResponse:
        return cls(
            id=row.id,
            question=row.question,
            answer=row.answer,
            category=row.category,
            locale=row.locale,
            sort_order=int(row.sort_order or 0),
            is_active=bool(row.is_active),
            created_by=row.created_by,
            updated_by=row.updated_by,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


class FaqItemListResponse(BaseModel):
    items: list[FaqItemResponse]
    total: int
    page: int
    limit: int
    has_more: bool


@router.get(
    "/faqs",
    response_model=FaqItemListResponse,
    summary="List FAQ items",
)
async def list_faqs_endpoint(
    session: SessionDep,
    admin: Annotated[User, Depends(require_role(ADMIN_CONTENT_MIN_ROLE))],
    search: Annotated[str | None, Query(max_length=128)] = None,
    category: Annotated[str | None, Query(max_length=64)] = None,
    locale: Annotated[str | None, Query(max_length=8)] = None,
    is_active: Annotated[bool | None, Query()] = None,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
) -> FaqItemListResponse:
    result = await list_faq_items(
        session,
        search=search,
        category=category,
        locale=locale,
        is_active=is_active,
        page=page,
        limit=limit,
    )
    return FaqItemListResponse(
        items=[FaqItemResponse.from_model(r) for r in result.items],
        total=result.total,
        page=result.page,
        limit=result.limit,
        has_more=result.has_more,
    )


@router.post(
    "/faqs",
    response_model=FaqItemResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a FAQ item",
)
async def create_faq_endpoint(
    payload: FaqItemPayload,
    request: Request,
    session: SessionDep,
    admin: Annotated[User, Depends(require_role(ADMIN_CONTENT_MIN_ROLE))],
) -> FaqItemResponse:
    ip, ua = _request_meta(request)
    draft = FaqItemDraft(**payload.model_dump())
    try:
        row = await create_faq_item(
            session, admin=admin, draft=draft, ip_address=ip, user_agent=ua
        )
    except InvalidContentPayloadError as exc:
        raise _payload_error(exc) from exc
    await _commit_or_500(session)
    return FaqItemResponse.from_model(row)


@router.get(
    "/faqs/{faq_id}",
    response_model=FaqItemResponse,
    summary="Fetch a FAQ item",
)
async def get_faq_endpoint(
    faq_id: int,
    session: SessionDep,
    admin: Annotated[User, Depends(require_role(ADMIN_CONTENT_MIN_ROLE))],
) -> FaqItemResponse:
    try:
        row = await get_faq_item(session, faq_id)
    except ContentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="faq_not_found",
        ) from exc
    return FaqItemResponse.from_model(row)


@router.put(
    "/faqs/{faq_id}",
    response_model=FaqItemResponse,
    summary="Update a FAQ item",
)
async def update_faq_endpoint(
    faq_id: int,
    payload: FaqItemPayload,
    request: Request,
    session: SessionDep,
    admin: Annotated[User, Depends(require_role(ADMIN_CONTENT_MIN_ROLE))],
) -> FaqItemResponse:
    ip, ua = _request_meta(request)
    draft = FaqItemDraft(**payload.model_dump())
    try:
        row = await update_faq_item(
            session,
            admin=admin,
            faq_id=faq_id,
            draft=draft,
            ip_address=ip,
            user_agent=ua,
        )
    except ContentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="faq_not_found",
        ) from exc
    except InvalidContentPayloadError as exc:
        raise _payload_error(exc) from exc
    await _commit_or_500(session)
    return FaqItemResponse.from_model(row)


@router.delete(
    "/faqs/{faq_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a FAQ item",
)
async def delete_faq_endpoint(
    faq_id: int,
    request: Request,
    session: SessionDep,
    admin: Annotated[User, Depends(require_role(ADMIN_CONTENT_MIN_ROLE))],
) -> None:
    ip, ua = _request_meta(request)
    try:
        await delete_faq_item(
            session, admin=admin, faq_id=faq_id, ip_address=ip, user_agent=ua
        )
    except ContentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="faq_not_found",
        ) from exc
    await _commit_or_500(session)
    return None


# ============================================================ welcome messages


class WelcomeMessagePayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    body: str = Field(..., min_length=1, max_length=8000)
    locale: str = Field(default="en", min_length=1, max_length=8)
    is_active: bool = False


class WelcomeMessageResponse(BaseModel):
    id: int
    name: str
    body: str
    locale: str
    is_active: bool
    created_by: int | None
    updated_by: int | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, row: WelcomeMessage) -> WelcomeMessageResponse:
        return cls(
            id=row.id,
            name=row.name,
            body=row.body,
            locale=row.locale,
            is_active=bool(row.is_active),
            created_by=row.created_by,
            updated_by=row.updated_by,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


class WelcomeMessageListResponse(BaseModel):
    items: list[WelcomeMessageResponse]
    total: int
    page: int
    limit: int
    has_more: bool


@router.get(
    "/welcomes",
    response_model=WelcomeMessageListResponse,
    summary="List welcome messages",
)
async def list_welcomes_endpoint(
    session: SessionDep,
    admin: Annotated[User, Depends(require_role(ADMIN_CONTENT_MIN_ROLE))],
    locale: Annotated[str | None, Query(max_length=8)] = None,
    is_active: Annotated[bool | None, Query()] = None,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
) -> WelcomeMessageListResponse:
    result = await list_welcome_messages(
        session,
        locale=locale,
        is_active=is_active,
        page=page,
        limit=limit,
    )
    return WelcomeMessageListResponse(
        items=[WelcomeMessageResponse.from_model(r) for r in result.items],
        total=result.total,
        page=result.page,
        limit=result.limit,
        has_more=result.has_more,
    )


@router.post(
    "/welcomes",
    response_model=WelcomeMessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a welcome message",
)
async def create_welcome_endpoint(
    payload: WelcomeMessagePayload,
    request: Request,
    session: SessionDep,
    admin: Annotated[User, Depends(require_role(ADMIN_CONTENT_MIN_ROLE))],
) -> WelcomeMessageResponse:
    ip, ua = _request_meta(request)
    draft = WelcomeMessageDraft(**payload.model_dump())
    try:
        row = await create_welcome_message(
            session, admin=admin, draft=draft, ip_address=ip, user_agent=ua
        )
    except InvalidContentPayloadError as exc:
        raise _payload_error(exc) from exc
    await _commit_or_500(session)
    return WelcomeMessageResponse.from_model(row)


@router.get(
    "/welcomes/{welcome_id}",
    response_model=WelcomeMessageResponse,
    summary="Fetch a welcome message",
)
async def get_welcome_endpoint(
    welcome_id: int,
    session: SessionDep,
    admin: Annotated[User, Depends(require_role(ADMIN_CONTENT_MIN_ROLE))],
) -> WelcomeMessageResponse:
    try:
        row = await get_welcome_message(session, welcome_id)
    except ContentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="welcome_not_found",
        ) from exc
    return WelcomeMessageResponse.from_model(row)


@router.put(
    "/welcomes/{welcome_id}",
    response_model=WelcomeMessageResponse,
    summary="Update a welcome message",
)
async def update_welcome_endpoint(
    welcome_id: int,
    payload: WelcomeMessagePayload,
    request: Request,
    session: SessionDep,
    admin: Annotated[User, Depends(require_role(ADMIN_CONTENT_MIN_ROLE))],
) -> WelcomeMessageResponse:
    ip, ua = _request_meta(request)
    draft = WelcomeMessageDraft(**payload.model_dump())
    try:
        row = await update_welcome_message(
            session,
            admin=admin,
            welcome_id=welcome_id,
            draft=draft,
            ip_address=ip,
            user_agent=ua,
        )
    except ContentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="welcome_not_found",
        ) from exc
    except InvalidContentPayloadError as exc:
        raise _payload_error(exc) from exc
    await _commit_or_500(session)
    return WelcomeMessageResponse.from_model(row)


@router.delete(
    "/welcomes/{welcome_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a welcome message",
)
async def delete_welcome_endpoint(
    welcome_id: int,
    request: Request,
    session: SessionDep,
    admin: Annotated[User, Depends(require_role(ADMIN_CONTENT_MIN_ROLE))],
) -> None:
    ip, ua = _request_meta(request)
    try:
        await delete_welcome_message(
            session,
            admin=admin,
            welcome_id=welcome_id,
            ip_address=ip,
            user_agent=ua,
        )
    except ContentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="welcome_not_found",
        ) from exc
    await _commit_or_500(session)
    return None


# ----------------------------------------------------------------- history


class AuditLogResponse(BaseModel):
    id: int
    admin_id: int
    target_user_id: int | None
    action: str
    payload: dict[str, Any] | None
    ip_address: str | None
    user_agent: str | None
    created_at: datetime

    @classmethod
    def from_model(cls, row: AdminAuditLog) -> AuditLogResponse:
        return cls(
            id=row.id,
            admin_id=row.admin_id,
            target_user_id=row.target_user_id,
            action=row.action,
            payload=row.payload,
            ip_address=row.ip_address,
            user_agent=row.user_agent,
            created_at=row.created_at,
        )


class AuditLogListResponse(BaseModel):
    items: list[AuditLogResponse]
    total: int
    page: int
    limit: int
    has_more: bool


ContentEntity = Literal["prompt_template", "faq_item", "welcome_message"]


@router.get(
    "/history",
    response_model=AuditLogListResponse,
    summary="Combined change history across all content types",
)
async def content_history_endpoint(
    session: SessionDep,
    admin: Annotated[User, Depends(require_role(ADMIN_CONTENT_MIN_ROLE))],
    entity: Annotated[ContentEntity | None, Query()] = None,
    entity_id: Annotated[int | None, Query(ge=1)] = None,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
) -> AuditLogListResponse:
    try:
        result = await list_content_history(
            session,
            entity=entity,
            entity_id=entity_id,
            page=page,
            limit=limit,
        )
    except InvalidContentPayloadError as exc:
        raise _payload_error(exc) from exc
    return AuditLogListResponse(
        items=[AuditLogResponse.from_model(r) for r in result.items],
        total=result.total,
        page=result.page,
        limit=result.limit,
        has_more=result.has_more,
    )


__all__ = [
    "AuditLogListResponse",
    "AuditLogResponse",
    "FaqItemListResponse",
    "FaqItemPayload",
    "FaqItemResponse",
    "PromptTemplateListResponse",
    "PromptTemplatePayload",
    "PromptTemplateResponse",
    "WelcomeMessageListResponse",
    "WelcomeMessagePayload",
    "WelcomeMessageResponse",
    "router",
]
