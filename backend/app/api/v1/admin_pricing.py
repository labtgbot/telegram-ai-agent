"""Admin dynamic pricing endpoints (Phase 3, issue #26).

Exposes three routes under ``/api/v1/admin/pricing``:

* ``GET /`` returns the current package overrides and global modifiers.
* ``POST /update`` persists a new config and writes an audit-log row in
  the same transaction.  Changes take effect on the next invoice (active
  subscription renewals are billed against the locked plan price, so
  they are intentionally **not** retroactive — see
  ``docs/PRICING_STRATEGY.md > Edge Cases``).
* ``GET /history`` is a thin wrapper around :func:`list_audit_log`
  filtered to ``action="pricing.update"``, so the UI can render a
  "who / when / what changed" feed without inventing a second table.

Reads require ``analyst`` (``get_current_admin``); writes require
``super_admin`` because pricing directly affects revenue.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from app.auth.dependencies import SessionDep, get_current_admin
from app.auth.rbac import Role, require_role
from app.core.client_ip import resolve_client_ip
from app.core.logging import get_logger
from app.models.admin_audit_log import AdminAuditLog
from app.models.user import User
from app.services.admin_users import list_audit_log
from app.services.pricing import (
    MAX_BONUS_TOKENS,
    MAX_DISCOUNT_PERCENT,
    MAX_STARS_PER_PACKAGE,
    MAX_TOKENS_PER_PACKAGE,
    PRICING_AUDIT_ACTION,
    InvalidPricingPayloadError,
    PricingConfig,
    PricingPackageOverride,
    PricingUpdateRequest,
    UnknownPackageError,
    load_pricing_config,
    update_pricing_config,
)

router = APIRouter(prefix="/admin/pricing", tags=["admin-pricing"])
logger = get_logger(__name__)


# ---------------------------------------------------------------- pydantic models


class PricingPackageModel(BaseModel):
    code: str
    title: str
    description: str
    tokens: int
    stars: int
    discount: int
    is_subscription: bool

    @classmethod
    def from_override(cls, override: PricingPackageOverride) -> PricingPackageModel:
        return cls(
            code=override.code,
            title=override.title,
            description=override.description,
            tokens=int(override.tokens),
            stars=int(override.stars),
            discount=int(override.discount),
            is_subscription=bool(override.is_subscription),
        )


class PricingConfigResponse(BaseModel):
    packages: list[PricingPackageModel]
    global_discount: int
    seasonal_promo: int
    first_purchase_bonus: int
    referral_bonus: int
    daily_bonus: int
    currency_rate: float
    limits: dict[str, int]

    @classmethod
    def from_config(cls, config: PricingConfig) -> PricingConfigResponse:
        return cls(
            packages=[
                PricingPackageModel.from_override(pkg) for pkg in config.packages
            ],
            global_discount=int(config.global_discount),
            seasonal_promo=int(config.seasonal_promo),
            first_purchase_bonus=int(config.first_purchase_bonus),
            referral_bonus=int(config.referral_bonus),
            daily_bonus=int(config.daily_bonus),
            currency_rate=float(config.currency_rate),
            limits={
                "max_discount_percent": MAX_DISCOUNT_PERCENT,
                "max_tokens_per_package": MAX_TOKENS_PER_PACKAGE,
                "max_stars_per_package": MAX_STARS_PER_PACKAGE,
                "max_bonus_tokens": MAX_BONUS_TOKENS,
            },
        )


class PricingPackageUpdate(BaseModel):
    """A single package override.

    All numeric fields are optional — omit to keep the current value.
    """

    tokens: int | None = Field(default=None, ge=1, le=MAX_TOKENS_PER_PACKAGE)
    stars: int | None = Field(default=None, ge=1, le=MAX_STARS_PER_PACKAGE)
    discount: int | None = Field(default=None, ge=0, le=MAX_DISCOUNT_PERCENT)


class PricingUpdatePayload(BaseModel):
    packages: dict[str, PricingPackageUpdate] = Field(default_factory=dict)
    global_discount: int | None = Field(
        default=None, ge=0, le=MAX_DISCOUNT_PERCENT
    )
    seasonal_promo: int | None = Field(
        default=None, ge=0, le=MAX_DISCOUNT_PERCENT
    )
    first_purchase_bonus: int | None = Field(
        default=None, ge=0, le=MAX_DISCOUNT_PERCENT
    )
    referral_bonus: int | None = Field(default=None, ge=0, le=MAX_BONUS_TOKENS)
    daily_bonus: int | None = Field(default=None, ge=0, le=MAX_BONUS_TOKENS)
    currency_rate: float | None = Field(default=None, ge=0, le=1000)


class PricingUpdateResponse(BaseModel):
    config: PricingConfigResponse
    diff: dict[str, Any]
    audit_log_id: int


class PricingHistoryItem(BaseModel):
    id: int
    admin_id: int
    diff: dict[str, Any] | None = None
    snapshot: dict[str, Any] | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    created_at: datetime

    @classmethod
    def from_row(cls, log: AdminAuditLog) -> PricingHistoryItem:
        payload = log.payload if isinstance(log.payload, dict) else None
        diff = None
        snapshot = None
        if payload is not None:
            raw_diff = payload.get("diff")
            if isinstance(raw_diff, dict):
                diff = raw_diff
            raw_snapshot = payload.get("config")
            if isinstance(raw_snapshot, dict):
                snapshot = raw_snapshot
        return cls(
            id=int(log.id),
            admin_id=int(log.admin_id),
            diff=diff,
            snapshot=snapshot,
            ip_address=log.ip_address,
            user_agent=log.user_agent,
            created_at=log.created_at,
        )


class PricingHistoryResponse(BaseModel):
    items: list[PricingHistoryItem]
    total: int
    page: int
    limit: int
    has_more: bool


# ---------------------------------------------------------------- helpers


def _request_meta(request: Request) -> tuple[str | None, str | None]:
    return resolve_client_ip(request), request.headers.get("user-agent")


async def _commit_or_500(session: Any) -> None:
    try:
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        logger.exception("admin.pricing.commit_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="commit_failed",
        ) from exc


# ---------------------------------------------------------------- endpoints


@router.get(
    "",
    response_model=PricingConfigResponse,
    summary="Current dynamic-pricing config (packages, discounts, bonuses)",
)
async def get_pricing_endpoint(
    session: SessionDep,
    admin: Annotated[User, Depends(get_current_admin)],
) -> PricingConfigResponse:
    config = await load_pricing_config(session)
    return PricingConfigResponse.from_config(config)


@router.post(
    "/update",
    response_model=PricingUpdateResponse,
    summary="Persist a new pricing config (super_admin only)",
)
async def update_pricing_endpoint(
    payload: PricingUpdatePayload,
    request: Request,
    session: SessionDep,
    admin: Annotated[User, Depends(require_role(Role.SUPER_ADMIN))],
) -> PricingUpdateResponse:
    ip, ua = _request_meta(request)
    request_obj = PricingUpdateRequest(
        packages={
            code: pkg.model_dump(exclude_none=True)
            for code, pkg in payload.packages.items()
        },
        global_discount=payload.global_discount,
        seasonal_promo=payload.seasonal_promo,
        first_purchase_bonus=payload.first_purchase_bonus,
        referral_bonus=payload.referral_bonus,
        daily_bonus=payload.daily_bonus,
        currency_rate=payload.currency_rate,
    )
    try:
        result = await update_pricing_config(
            session,
            admin=admin,
            payload=request_obj,
            ip_address=ip,
            user_agent=ua,
        )
    except UnknownPackageError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "unknown_package", "message": str(exc)},
        ) from exc
    except InvalidPricingPayloadError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_pricing_payload", "message": str(exc)},
        ) from exc

    await _commit_or_500(session)
    return PricingUpdateResponse(
        config=PricingConfigResponse.from_config(result.config),
        diff=result.diff,
        audit_log_id=result.audit_log_id,
    )


@router.get(
    "/history",
    response_model=PricingHistoryResponse,
    summary="Audit history of pricing changes (newest first)",
)
async def get_pricing_history_endpoint(
    session: SessionDep,
    admin: Annotated[User, Depends(get_current_admin)],
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
) -> PricingHistoryResponse:
    result = await list_audit_log(
        session,
        action=PRICING_AUDIT_ACTION,
        page=page,
        limit=limit,
    )
    return PricingHistoryResponse(
        items=[PricingHistoryItem.from_row(row) for row in result.items],
        total=result.total,
        page=result.page,
        limit=result.limit,
        has_more=result.has_more,
    )
