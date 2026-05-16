"""Admin content management service (Phase 3, issue #29).

Powers the CRM "Content" section: CRUD for prompt templates, FAQ items
and welcome messages.  Every mutation writes a row to ``admin_audit_logs``
so support engineers always have a tamper-evident change history.

The service is intentionally split into small, dataclass-driven
functions so the HTTP layer can compose them without bringing the
entire surface area in scope.  Each entity follows the same shape:

* ``XxxDraft`` — input payload for create/update (Pydantic-friendly).
* ``list_xxx`` — paginated, filtered listing.
* ``get_xxx`` — single-row read; raises :class:`ContentNotFoundError`.
* ``create_xxx`` / ``update_xxx`` / ``delete_xxx`` — mutations + audit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Select, and_, asc, desc, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.admin_audit_log import AdminAuditLog
from app.models.faq_item import FaqItem
from app.models.prompt_template import PromptTemplate
from app.models.user import User
from app.models.welcome_message import WelcomeMessage

logger = get_logger(__name__)


# ---------------------------------------------------------------- constants

DEFAULT_LIMIT = 25
MAX_LIMIT = 200

MAX_CODE_LEN = 64
MAX_TITLE_LEN = 255
MAX_BODY_LEN = 8000
MAX_CATEGORY_LEN = 64
MAX_LOCALE_LEN = 8
MAX_QUESTION_LEN = 512
MAX_NAME_LEN = 120

# Audit action constants.
PROMPT_AUDIT_CREATE = "prompt_template.create"
PROMPT_AUDIT_UPDATE = "prompt_template.update"
PROMPT_AUDIT_DELETE = "prompt_template.delete"

FAQ_AUDIT_CREATE = "faq_item.create"
FAQ_AUDIT_UPDATE = "faq_item.update"
FAQ_AUDIT_DELETE = "faq_item.delete"

WELCOME_AUDIT_CREATE = "welcome_message.create"
WELCOME_AUDIT_UPDATE = "welcome_message.update"
WELCOME_AUDIT_DELETE = "welcome_message.delete"


# ---------------------------------------------------------------- exceptions


class ContentError(Exception):
    """Base class for content service failures."""


class ContentNotFoundError(ContentError):
    """The referenced entity does not exist."""


class InvalidContentPayloadError(ContentError):
    """Caller supplied a malformed payload."""


class DuplicateContentCodeError(ContentError):
    """A unique field (e.g. ``prompt_templates.code``) collided."""


# ---------------------------------------------------------------- dataclasses


@dataclass(frozen=True)
class PromptTemplateDraft:
    code: str
    title: str
    body: str
    category: str | None = None
    locale: str = "en"
    sort_order: int = 0
    is_active: bool = True


@dataclass(frozen=True)
class FaqItemDraft:
    question: str
    answer: str
    category: str | None = None
    locale: str = "en"
    sort_order: int = 0
    is_active: bool = True


@dataclass(frozen=True)
class WelcomeMessageDraft:
    name: str
    body: str
    locale: str = "en"
    is_active: bool = False


@dataclass(frozen=True)
class ContentListPage:
    items: list[Any]
    total: int
    page: int
    limit: int
    has_more: bool = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "has_more", (self.page * self.limit) < self.total)


# ---------------------------------------------------------------- helpers


def _normalise_str(value: str | None, *, max_len: int, field: str, required: bool = True) -> str | None:
    raw = (value or "").strip()
    if not raw:
        if required:
            raise InvalidContentPayloadError(f"{field} is required")
        return None
    if len(raw) > max_len:
        raise InvalidContentPayloadError(f"{field} exceeds {max_len} characters")
    return raw


def _coerce_pagination(page: int, limit: int) -> tuple[int, int, int]:
    page = max(int(page or 1), 1)
    limit = max(min(int(limit or DEFAULT_LIMIT), MAX_LIMIT), 1)
    offset = (page - 1) * limit
    return page, limit, offset


# ============================================================ prompt templates


def _apply_prompt_filters(
    stmt: Select[Any],
    *,
    search: str | None,
    category: str | None,
    locale: str | None,
    is_active: bool | None,
) -> Select[Any]:
    if search:
        like = f"%{search.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(PromptTemplate.code).like(like),
                func.lower(PromptTemplate.title).like(like),
                func.lower(PromptTemplate.body).like(like),
            )
        )
    if category:
        stmt = stmt.where(PromptTemplate.category == category)
    if locale:
        stmt = stmt.where(PromptTemplate.locale == locale)
    if is_active is not None:
        stmt = stmt.where(PromptTemplate.is_active.is_(is_active))
    return stmt


async def list_prompt_templates(
    session: AsyncSession,
    *,
    search: str | None = None,
    category: str | None = None,
    locale: str | None = None,
    is_active: bool | None = None,
    page: int = 1,
    limit: int = DEFAULT_LIMIT,
) -> ContentListPage:
    page, limit, offset = _coerce_pagination(page, limit)
    count_stmt = _apply_prompt_filters(
        select(func.count()).select_from(PromptTemplate),
        search=search,
        category=category,
        locale=locale,
        is_active=is_active,
    )
    rows_stmt = _apply_prompt_filters(
        select(PromptTemplate),
        search=search,
        category=category,
        locale=locale,
        is_active=is_active,
    ).order_by(
        asc(PromptTemplate.sort_order),
        desc(PromptTemplate.updated_at),
        desc(PromptTemplate.id),
    ).offset(offset).limit(limit)

    total = int((await session.execute(count_stmt)).scalar_one())
    items = list((await session.execute(rows_stmt)).scalars().all())
    return ContentListPage(items=items, total=total, page=page, limit=limit)


async def get_prompt_template(session: AsyncSession, template_id: int) -> PromptTemplate:
    template = await session.get(PromptTemplate, template_id)
    if template is None:
        raise ContentNotFoundError(f"prompt template {template_id} not found")
    return template


def _clean_prompt_draft(draft: PromptTemplateDraft) -> PromptTemplateDraft:
    code = _normalise_str(draft.code, max_len=MAX_CODE_LEN, field="code")
    title = _normalise_str(draft.title, max_len=MAX_TITLE_LEN, field="title")
    body = _normalise_str(draft.body, max_len=MAX_BODY_LEN, field="body")
    category = _normalise_str(
        draft.category, max_len=MAX_CATEGORY_LEN, field="category", required=False
    )
    locale = _normalise_str(
        draft.locale, max_len=MAX_LOCALE_LEN, field="locale", required=True
    ) or "en"
    return PromptTemplateDraft(
        code=code or "",
        title=title or "",
        body=body or "",
        category=category,
        locale=locale,
        sort_order=int(draft.sort_order or 0),
        is_active=bool(draft.is_active),
    )


async def create_prompt_template(
    session: AsyncSession,
    *,
    admin: User,
    draft: PromptTemplateDraft,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> PromptTemplate:
    cleaned = _clean_prompt_draft(draft)
    template = PromptTemplate(
        code=cleaned.code,
        title=cleaned.title,
        body=cleaned.body,
        category=cleaned.category,
        locale=cleaned.locale,
        sort_order=cleaned.sort_order,
        is_active=cleaned.is_active,
        created_by=admin.id,
        updated_by=admin.id,
    )
    session.add(template)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise DuplicateContentCodeError(
            f"prompt template code={cleaned.code!r} already exists"
        ) from exc

    session.add(
        _audit(
            admin=admin,
            action=PROMPT_AUDIT_CREATE,
            payload={
                "id": template.id,
                "code": template.code,
                "title": template.title,
                "locale": template.locale,
                "is_active": template.is_active,
            },
            ip_address=ip_address,
            user_agent=user_agent,
        )
    )
    await session.flush()
    logger.info(
        "prompt_template.created",
        id=template.id,
        admin_id=admin.id,
        code=template.code,
    )
    return template


async def update_prompt_template(
    session: AsyncSession,
    *,
    admin: User,
    template_id: int,
    draft: PromptTemplateDraft,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> PromptTemplate:
    template = await get_prompt_template(session, template_id)
    cleaned = _clean_prompt_draft(draft)

    before = {
        "code": template.code,
        "title": template.title,
        "category": template.category,
        "locale": template.locale,
        "sort_order": template.sort_order,
        "is_active": template.is_active,
    }

    template.code = cleaned.code
    template.title = cleaned.title
    template.body = cleaned.body
    template.category = cleaned.category
    template.locale = cleaned.locale
    template.sort_order = cleaned.sort_order
    template.is_active = cleaned.is_active
    template.updated_by = admin.id

    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise DuplicateContentCodeError(
            f"prompt template code={cleaned.code!r} already exists"
        ) from exc

    session.add(
        _audit(
            admin=admin,
            action=PROMPT_AUDIT_UPDATE,
            payload={
                "id": template.id,
                "before": before,
                "after": {
                    "code": template.code,
                    "title": template.title,
                    "category": template.category,
                    "locale": template.locale,
                    "sort_order": template.sort_order,
                    "is_active": template.is_active,
                },
            },
            ip_address=ip_address,
            user_agent=user_agent,
        )
    )
    await session.flush()
    return template


async def delete_prompt_template(
    session: AsyncSession,
    *,
    admin: User,
    template_id: int,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    template = await get_prompt_template(session, template_id)
    snapshot = {
        "id": template.id,
        "code": template.code,
        "title": template.title,
        "locale": template.locale,
        "is_active": template.is_active,
    }
    await session.delete(template)
    session.add(
        _audit(
            admin=admin,
            action=PROMPT_AUDIT_DELETE,
            payload=snapshot,
            ip_address=ip_address,
            user_agent=user_agent,
        )
    )
    await session.flush()


# ================================================================ FAQ items


def _apply_faq_filters(
    stmt: Select[Any],
    *,
    search: str | None,
    category: str | None,
    locale: str | None,
    is_active: bool | None,
) -> Select[Any]:
    if search:
        like = f"%{search.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(FaqItem.question).like(like),
                func.lower(FaqItem.answer).like(like),
            )
        )
    if category:
        stmt = stmt.where(FaqItem.category == category)
    if locale:
        stmt = stmt.where(FaqItem.locale == locale)
    if is_active is not None:
        stmt = stmt.where(FaqItem.is_active.is_(is_active))
    return stmt


async def list_faq_items(
    session: AsyncSession,
    *,
    search: str | None = None,
    category: str | None = None,
    locale: str | None = None,
    is_active: bool | None = None,
    page: int = 1,
    limit: int = DEFAULT_LIMIT,
) -> ContentListPage:
    page, limit, offset = _coerce_pagination(page, limit)
    count_stmt = _apply_faq_filters(
        select(func.count()).select_from(FaqItem),
        search=search,
        category=category,
        locale=locale,
        is_active=is_active,
    )
    rows_stmt = _apply_faq_filters(
        select(FaqItem),
        search=search,
        category=category,
        locale=locale,
        is_active=is_active,
    ).order_by(
        asc(FaqItem.sort_order),
        desc(FaqItem.updated_at),
        desc(FaqItem.id),
    ).offset(offset).limit(limit)

    total = int((await session.execute(count_stmt)).scalar_one())
    items = list((await session.execute(rows_stmt)).scalars().all())
    return ContentListPage(items=items, total=total, page=page, limit=limit)


async def get_faq_item(session: AsyncSession, faq_id: int) -> FaqItem:
    faq = await session.get(FaqItem, faq_id)
    if faq is None:
        raise ContentNotFoundError(f"faq item {faq_id} not found")
    return faq


def _clean_faq_draft(draft: FaqItemDraft) -> FaqItemDraft:
    question = _normalise_str(draft.question, max_len=MAX_QUESTION_LEN, field="question")
    answer = _normalise_str(draft.answer, max_len=MAX_BODY_LEN, field="answer")
    category = _normalise_str(
        draft.category, max_len=MAX_CATEGORY_LEN, field="category", required=False
    )
    locale = _normalise_str(
        draft.locale, max_len=MAX_LOCALE_LEN, field="locale", required=True
    ) or "en"
    return FaqItemDraft(
        question=question or "",
        answer=answer or "",
        category=category,
        locale=locale,
        sort_order=int(draft.sort_order or 0),
        is_active=bool(draft.is_active),
    )


async def create_faq_item(
    session: AsyncSession,
    *,
    admin: User,
    draft: FaqItemDraft,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> FaqItem:
    cleaned = _clean_faq_draft(draft)
    faq = FaqItem(
        question=cleaned.question,
        answer=cleaned.answer,
        category=cleaned.category,
        locale=cleaned.locale,
        sort_order=cleaned.sort_order,
        is_active=cleaned.is_active,
        created_by=admin.id,
        updated_by=admin.id,
    )
    session.add(faq)
    await session.flush()

    session.add(
        _audit(
            admin=admin,
            action=FAQ_AUDIT_CREATE,
            payload={
                "id": faq.id,
                "question": faq.question,
                "category": faq.category,
                "locale": faq.locale,
                "is_active": faq.is_active,
            },
            ip_address=ip_address,
            user_agent=user_agent,
        )
    )
    await session.flush()
    return faq


async def update_faq_item(
    session: AsyncSession,
    *,
    admin: User,
    faq_id: int,
    draft: FaqItemDraft,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> FaqItem:
    faq = await get_faq_item(session, faq_id)
    cleaned = _clean_faq_draft(draft)

    before = {
        "question": faq.question,
        "category": faq.category,
        "locale": faq.locale,
        "sort_order": faq.sort_order,
        "is_active": faq.is_active,
    }
    faq.question = cleaned.question
    faq.answer = cleaned.answer
    faq.category = cleaned.category
    faq.locale = cleaned.locale
    faq.sort_order = cleaned.sort_order
    faq.is_active = cleaned.is_active
    faq.updated_by = admin.id
    await session.flush()

    session.add(
        _audit(
            admin=admin,
            action=FAQ_AUDIT_UPDATE,
            payload={
                "id": faq.id,
                "before": before,
                "after": {
                    "question": faq.question,
                    "category": faq.category,
                    "locale": faq.locale,
                    "sort_order": faq.sort_order,
                    "is_active": faq.is_active,
                },
            },
            ip_address=ip_address,
            user_agent=user_agent,
        )
    )
    await session.flush()
    return faq


async def delete_faq_item(
    session: AsyncSession,
    *,
    admin: User,
    faq_id: int,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    faq = await get_faq_item(session, faq_id)
    snapshot = {
        "id": faq.id,
        "question": faq.question,
        "category": faq.category,
        "locale": faq.locale,
        "is_active": faq.is_active,
    }
    await session.delete(faq)
    session.add(
        _audit(
            admin=admin,
            action=FAQ_AUDIT_DELETE,
            payload=snapshot,
            ip_address=ip_address,
            user_agent=user_agent,
        )
    )
    await session.flush()


# =========================================================== welcome messages


def _apply_welcome_filters(
    stmt: Select[Any],
    *,
    locale: str | None,
    is_active: bool | None,
) -> Select[Any]:
    if locale:
        stmt = stmt.where(WelcomeMessage.locale == locale)
    if is_active is not None:
        stmt = stmt.where(WelcomeMessage.is_active.is_(is_active))
    return stmt


async def list_welcome_messages(
    session: AsyncSession,
    *,
    locale: str | None = None,
    is_active: bool | None = None,
    page: int = 1,
    limit: int = DEFAULT_LIMIT,
) -> ContentListPage:
    page, limit, offset = _coerce_pagination(page, limit)
    count_stmt = _apply_welcome_filters(
        select(func.count()).select_from(WelcomeMessage),
        locale=locale,
        is_active=is_active,
    )
    rows_stmt = _apply_welcome_filters(
        select(WelcomeMessage),
        locale=locale,
        is_active=is_active,
    ).order_by(
        asc(WelcomeMessage.locale),
        desc(WelcomeMessage.is_active),
        desc(WelcomeMessage.updated_at),
        desc(WelcomeMessage.id),
    ).offset(offset).limit(limit)

    total = int((await session.execute(count_stmt)).scalar_one())
    items = list((await session.execute(rows_stmt)).scalars().all())
    return ContentListPage(items=items, total=total, page=page, limit=limit)


async def get_welcome_message(session: AsyncSession, welcome_id: int) -> WelcomeMessage:
    welcome = await session.get(WelcomeMessage, welcome_id)
    if welcome is None:
        raise ContentNotFoundError(f"welcome message {welcome_id} not found")
    return welcome


def _clean_welcome_draft(draft: WelcomeMessageDraft) -> WelcomeMessageDraft:
    name = _normalise_str(draft.name, max_len=MAX_NAME_LEN, field="name")
    body = _normalise_str(draft.body, max_len=MAX_BODY_LEN, field="body")
    locale = _normalise_str(
        draft.locale, max_len=MAX_LOCALE_LEN, field="locale", required=True
    ) or "en"
    return WelcomeMessageDraft(
        name=name or "",
        body=body or "",
        locale=locale,
        is_active=bool(draft.is_active),
    )


async def _deactivate_other_welcomes(
    session: AsyncSession,
    *,
    locale: str,
    keep_id: int | None,
) -> None:
    stmt = update(WelcomeMessage).where(
        WelcomeMessage.locale == locale,
        WelcomeMessage.is_active.is_(True),
    )
    if keep_id is not None:
        stmt = stmt.where(WelcomeMessage.id != keep_id)
    await session.execute(stmt.values(is_active=False))


async def create_welcome_message(
    session: AsyncSession,
    *,
    admin: User,
    draft: WelcomeMessageDraft,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> WelcomeMessage:
    cleaned = _clean_welcome_draft(draft)
    if cleaned.is_active:
        await _deactivate_other_welcomes(
            session, locale=cleaned.locale, keep_id=None
        )

    welcome = WelcomeMessage(
        name=cleaned.name,
        body=cleaned.body,
        locale=cleaned.locale,
        is_active=cleaned.is_active,
        created_by=admin.id,
        updated_by=admin.id,
    )
    session.add(welcome)
    await session.flush()

    session.add(
        _audit(
            admin=admin,
            action=WELCOME_AUDIT_CREATE,
            payload={
                "id": welcome.id,
                "name": welcome.name,
                "locale": welcome.locale,
                "is_active": welcome.is_active,
            },
            ip_address=ip_address,
            user_agent=user_agent,
        )
    )
    await session.flush()
    return welcome


async def update_welcome_message(
    session: AsyncSession,
    *,
    admin: User,
    welcome_id: int,
    draft: WelcomeMessageDraft,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> WelcomeMessage:
    welcome = await get_welcome_message(session, welcome_id)
    cleaned = _clean_welcome_draft(draft)

    before = {
        "name": welcome.name,
        "locale": welcome.locale,
        "is_active": welcome.is_active,
    }

    if cleaned.is_active:
        await _deactivate_other_welcomes(
            session, locale=cleaned.locale, keep_id=welcome.id
        )

    welcome.name = cleaned.name
    welcome.body = cleaned.body
    welcome.locale = cleaned.locale
    welcome.is_active = cleaned.is_active
    welcome.updated_by = admin.id
    await session.flush()

    session.add(
        _audit(
            admin=admin,
            action=WELCOME_AUDIT_UPDATE,
            payload={
                "id": welcome.id,
                "before": before,
                "after": {
                    "name": welcome.name,
                    "locale": welcome.locale,
                    "is_active": welcome.is_active,
                },
            },
            ip_address=ip_address,
            user_agent=user_agent,
        )
    )
    await session.flush()
    return welcome


async def delete_welcome_message(
    session: AsyncSession,
    *,
    admin: User,
    welcome_id: int,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    welcome = await get_welcome_message(session, welcome_id)
    snapshot = {
        "id": welcome.id,
        "name": welcome.name,
        "locale": welcome.locale,
        "is_active": welcome.is_active,
    }
    await session.delete(welcome)
    session.add(
        _audit(
            admin=admin,
            action=WELCOME_AUDIT_DELETE,
            payload=snapshot,
            ip_address=ip_address,
            user_agent=user_agent,
        )
    )
    await session.flush()


# ----------------------------------------------------------------- audit helper


def _audit(
    *,
    admin: User,
    action: str,
    payload: dict[str, Any] | None,
    ip_address: str | None,
    user_agent: str | None,
) -> AdminAuditLog:
    return AdminAuditLog(
        admin_id=admin.id,
        target_user_id=None,
        action=action[:64],
        payload=payload,
        ip_address=(ip_address or "")[:64] or None,
        user_agent=(user_agent or "")[:512] or None,
    )


# ------------------------------------------------------------- content history


CONTENT_ACTIONS: tuple[str, ...] = (
    PROMPT_AUDIT_CREATE,
    PROMPT_AUDIT_UPDATE,
    PROMPT_AUDIT_DELETE,
    FAQ_AUDIT_CREATE,
    FAQ_AUDIT_UPDATE,
    FAQ_AUDIT_DELETE,
    WELCOME_AUDIT_CREATE,
    WELCOME_AUDIT_UPDATE,
    WELCOME_AUDIT_DELETE,
)


async def list_content_history(
    session: AsyncSession,
    *,
    entity: str | None = None,
    entity_id: int | None = None,
    page: int = 1,
    limit: int = DEFAULT_LIMIT,
) -> ContentListPage:
    """Return ``admin_audit_logs`` rows scoped to content mutations.

    ``entity`` is one of ``"prompt_template"``, ``"faq_item"``,
    ``"welcome_message"`` — when set, only that family's actions are
    returned.  ``entity_id`` further narrows the result to a single row
    by JSON-extracting ``payload->>'id'``.
    """
    page, limit, offset = _coerce_pagination(page, limit)
    conditions: list[Any] = []

    if entity:
        prefix = f"{entity}."
        actions = tuple(a for a in CONTENT_ACTIONS if a.startswith(prefix))
        if not actions:
            raise InvalidContentPayloadError(f"unknown entity={entity!r}")
        conditions.append(AdminAuditLog.action.in_(actions))
    else:
        conditions.append(AdminAuditLog.action.in_(CONTENT_ACTIONS))

    if entity_id is not None:
        conditions.append(
            AdminAuditLog.payload["id"].astext == str(int(entity_id))
        )

    where = and_(*conditions)
    count_stmt = select(func.count()).select_from(AdminAuditLog).where(where)
    rows_stmt = (
        select(AdminAuditLog)
        .where(where)
        .order_by(AdminAuditLog.created_at.desc(), AdminAuditLog.id.desc())
        .offset(offset)
        .limit(limit)
    )

    total = int((await session.execute(count_stmt)).scalar_one())
    items = list((await session.execute(rows_stmt)).scalars().all())
    return ContentListPage(items=items, total=total, page=page, limit=limit)


__all__ = [
    "CONTENT_ACTIONS",
    "ContentError",
    "ContentListPage",
    "ContentNotFoundError",
    "DuplicateContentCodeError",
    "FAQ_AUDIT_CREATE",
    "FAQ_AUDIT_DELETE",
    "FAQ_AUDIT_UPDATE",
    "FaqItemDraft",
    "InvalidContentPayloadError",
    "PROMPT_AUDIT_CREATE",
    "PROMPT_AUDIT_DELETE",
    "PROMPT_AUDIT_UPDATE",
    "PromptTemplateDraft",
    "WELCOME_AUDIT_CREATE",
    "WELCOME_AUDIT_DELETE",
    "WELCOME_AUDIT_UPDATE",
    "WelcomeMessageDraft",
    "create_faq_item",
    "create_prompt_template",
    "create_welcome_message",
    "delete_faq_item",
    "delete_prompt_template",
    "delete_welcome_message",
    "get_faq_item",
    "get_prompt_template",
    "get_welcome_message",
    "list_content_history",
    "list_faq_items",
    "list_prompt_templates",
    "list_welcome_messages",
    "update_faq_item",
    "update_prompt_template",
    "update_welcome_message",
]
