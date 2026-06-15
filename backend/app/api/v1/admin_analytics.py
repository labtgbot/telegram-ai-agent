"""Admin analytics endpoints (Phase 3, issue #27).

Exposes four read-only routes under ``/api/v1/admin/analytics``:

* ``GET /revenue`` — purchases grouped by day / week / month.
* ``GET /user-behavior`` — funnel (registered → activated → paid →
  repeat → premium) plus a weekly retention matrix.
* ``GET /ltv`` — lifetime-value per monthly cohort.
* ``GET /tokens`` — token spend per service over a window (powers the
  "Tokens" tab and feeds the CSV export).
* ``GET /export.csv`` — same revenue payload as ``/revenue`` rendered
  as CSV; writes an audit-log row.

Read routes are gated to ``analyst`` and above.  CSV export requires
``support_admin`` because it creates an auditable data extract.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from app.auth.admin_access import ADMIN_ANALYTICS_EXPORT_MIN_ROLE
from app.auth.dependencies import SessionDep, get_current_admin
from app.auth.rbac import require_role
from app.core.client_ip import resolve_client_ip
from app.core.logging import get_logger
from app.models.user import User
from app.services.admin_users import record_audit_event
from app.services.analytics import (
    ANALYTICS_AUDIT_EXPORT,
    DEFAULT_LTV_COHORT_MONTHS,
    DEFAULT_RETENTION_WEEKS,
    FunnelStage,
    InvalidRangeError,
    LtvCohort,
    LtvSummary,
    RetentionRow,
    RevenuePoint,
    RevenueSummary,
    TokenUsagePoint,
    TokenUsageSummary,
    UnsupportedGroupingError,
    UserBehavior,
    get_ltv_summary,
    get_revenue_summary,
    get_token_usage,
    get_user_behavior,
    revenue_csv,
)

router = APIRouter(prefix="/admin/analytics", tags=["admin-analytics"])
logger = get_logger(__name__)


# ---------------------------------------------------------------- helpers


def _request_meta(request: Request) -> tuple[str | None, str | None]:
    return resolve_client_ip(request), request.headers.get("user-agent")


async def _commit_or_500(session: Any) -> None:
    try:
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        logger.exception("admin.analytics.commit_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="commit_failed",
        ) from exc


def _map_range_errors(exc: Exception) -> HTTPException:
    if isinstance(exc, InvalidRangeError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_range", "message": str(exc)},
        )
    if isinstance(exc, UnsupportedGroupingError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_group_by", "message": str(exc)},
        )
    return HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------- pydantic models


class RevenuePointModel(BaseModel):
    bucket: date
    purchases: int
    stars: int
    usd: Decimal
    tokens_sold: int

    @classmethod
    def from_dc(cls, point: RevenuePoint) -> RevenuePointModel:
        return cls(
            bucket=point.bucket,
            purchases=point.purchases,
            stars=point.stars,
            usd=point.usd,
            tokens_sold=point.tokens_sold,
        )


class RevenueResponse(BaseModel):
    start_date: date
    end_date: date
    group_by: str
    total_stars: int
    total_usd: Decimal
    total_tokens_sold: int
    total_purchases: int
    points: list[RevenuePointModel]

    @classmethod
    def from_dc(cls, summary: RevenueSummary) -> RevenueResponse:
        return cls(
            start_date=summary.start_date,
            end_date=summary.end_date,
            group_by=summary.group_by,
            total_stars=summary.total_stars,
            total_usd=summary.total_usd,
            total_tokens_sold=summary.total_tokens_sold,
            total_purchases=summary.total_purchases,
            points=[RevenuePointModel.from_dc(p) for p in summary.points],
        )


class FunnelStageModel(BaseModel):
    key: str
    label: str
    users: int
    conversion_from_previous: float
    conversion_from_top: float

    @classmethod
    def from_dc(cls, stage: FunnelStage) -> FunnelStageModel:
        return cls(
            key=stage.key,
            label=stage.label,
            users=stage.users,
            conversion_from_previous=stage.conversion_from_previous,
            conversion_from_top=stage.conversion_from_top,
        )


class RetentionRowModel(BaseModel):
    cohort: date
    cohort_size: int
    retained: list[int]
    rates: list[float]

    @classmethod
    def from_dc(cls, row: RetentionRow) -> RetentionRowModel:
        return cls(
            cohort=row.cohort,
            cohort_size=row.cohort_size,
            retained=list(row.retained),
            rates=list(row.rates),
        )


class UserBehaviorResponse(BaseModel):
    start_date: date
    end_date: date
    retention_weeks: int
    funnel: list[FunnelStageModel]
    retention: list[RetentionRowModel]

    @classmethod
    def from_dc(cls, behavior: UserBehavior) -> UserBehaviorResponse:
        return cls(
            start_date=behavior.start_date,
            end_date=behavior.end_date,
            retention_weeks=behavior.retention_weeks,
            funnel=[FunnelStageModel.from_dc(s) for s in behavior.funnel],
            retention=[RetentionRowModel.from_dc(r) for r in behavior.retention],
        )


class LtvCohortModel(BaseModel):
    cohort: date
    cohort_size: int
    paying_users: int
    revenue_stars: int
    revenue_usd: Decimal
    ltv_stars: float
    ltv_usd: float
    avg_revenue_per_paying: float

    @classmethod
    def from_dc(cls, cohort: LtvCohort) -> LtvCohortModel:
        return cls(
            cohort=cohort.cohort,
            cohort_size=cohort.cohort_size,
            paying_users=cohort.paying_users,
            revenue_stars=cohort.revenue_stars,
            revenue_usd=cohort.revenue_usd,
            ltv_stars=cohort.ltv_stars,
            ltv_usd=cohort.ltv_usd,
            avg_revenue_per_paying=cohort.avg_revenue_per_paying,
        )


class LtvResponse(BaseModel):
    months: int
    overall_arpu_stars: float
    overall_arpu_usd: float
    overall_paying_rate: float
    cohorts: list[LtvCohortModel]

    @classmethod
    def from_dc(cls, summary: LtvSummary) -> LtvResponse:
        return cls(
            months=summary.months,
            overall_arpu_stars=summary.overall_arpu_stars,
            overall_arpu_usd=summary.overall_arpu_usd,
            overall_paying_rate=summary.overall_paying_rate,
            cohorts=[LtvCohortModel.from_dc(c) for c in summary.cohorts],
        )


class TokenUsagePointModel(BaseModel):
    service_type: str
    requests: int
    tokens_spent: int
    share: float

    @classmethod
    def from_dc(cls, point: TokenUsagePoint) -> TokenUsagePointModel:
        return cls(
            service_type=point.service_type,
            requests=point.requests,
            tokens_spent=point.tokens_spent,
            share=point.share,
        )


class TokenUsageResponse(BaseModel):
    start_date: date
    end_date: date
    total_requests: int
    total_tokens_spent: int
    services: list[TokenUsagePointModel]

    @classmethod
    def from_dc(cls, summary: TokenUsageSummary) -> TokenUsageResponse:
        return cls(
            start_date=summary.start_date,
            end_date=summary.end_date,
            total_requests=summary.total_requests,
            total_tokens_spent=summary.total_tokens_spent,
            services=[TokenUsagePointModel.from_dc(s) for s in summary.services],
        )


# ---------------------------------------------------------------- endpoints


@router.get(
    "/revenue",
    response_model=RevenueResponse,
    summary="Revenue trend bucketed by day, week or month",
)
async def get_revenue_endpoint(
    session: SessionDep,
    admin: Annotated[User, Depends(get_current_admin)],
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
    group_by: Annotated[str, Query(pattern="^(day|week|month)$")] = "day",
) -> RevenueResponse:
    try:
        summary = await get_revenue_summary(
            session,
            start_date=start_date,
            end_date=end_date,
            group_by=group_by,
        )
    except (InvalidRangeError, UnsupportedGroupingError) as exc:
        raise _map_range_errors(exc) from exc
    return RevenueResponse.from_dc(summary)


@router.get(
    "/user-behavior",
    response_model=UserBehaviorResponse,
    summary="Funnel + weekly retention for users registered in the window",
)
async def get_user_behavior_endpoint(
    session: SessionDep,
    admin: Annotated[User, Depends(get_current_admin)],
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
    retention_weeks: Annotated[
        int, Query(ge=1, le=26)
    ] = DEFAULT_RETENTION_WEEKS,
) -> UserBehaviorResponse:
    try:
        behavior = await get_user_behavior(
            session,
            start_date=start_date,
            end_date=end_date,
            retention_weeks=retention_weeks,
        )
    except InvalidRangeError as exc:
        raise _map_range_errors(exc) from exc
    return UserBehaviorResponse.from_dc(behavior)


@router.get(
    "/ltv",
    response_model=LtvResponse,
    summary="Lifetime value per monthly registration cohort",
)
async def get_ltv_endpoint(
    session: SessionDep,
    admin: Annotated[User, Depends(get_current_admin)],
    months: Annotated[int, Query(ge=1, le=24)] = DEFAULT_LTV_COHORT_MONTHS,
) -> LtvResponse:
    summary = await get_ltv_summary(session, months=months)
    return LtvResponse.from_dc(summary)


@router.get(
    "/tokens",
    response_model=TokenUsageResponse,
    summary="Token spend per service over a date window",
)
async def get_tokens_endpoint(
    session: SessionDep,
    admin: Annotated[User, Depends(get_current_admin)],
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
) -> TokenUsageResponse:
    try:
        summary = await get_token_usage(
            session, start_date=start_date, end_date=end_date
        )
    except InvalidRangeError as exc:
        raise _map_range_errors(exc) from exc
    return TokenUsageResponse.from_dc(summary)


@router.get(
    "/export.csv",
    response_class=PlainTextResponse,
    summary="CSV export of the revenue trend",
)
async def export_revenue_csv_endpoint(
    request: Request,
    session: SessionDep,
    admin: Annotated[User, Depends(require_role(ADMIN_ANALYTICS_EXPORT_MIN_ROLE))],
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
    group_by: Annotated[str, Query(pattern="^(day|week|month)$")] = "day",
) -> PlainTextResponse:
    try:
        summary = await get_revenue_summary(
            session,
            start_date=start_date,
            end_date=end_date,
            group_by=group_by,
        )
    except (InvalidRangeError, UnsupportedGroupingError) as exc:
        raise _map_range_errors(exc) from exc

    body = revenue_csv(summary)
    ip, ua = _request_meta(request)
    await record_audit_event(
        session,
        admin=admin,
        target_user_id=None,
        action=ANALYTICS_AUDIT_EXPORT,
        payload={
            "kind": "revenue",
            "start_date": summary.start_date.isoformat(),
            "end_date": summary.end_date.isoformat(),
            "group_by": summary.group_by,
            "rows": len(summary.points),
        },
        ip_address=ip,
        user_agent=ua,
    )
    await _commit_or_500(session)

    filename = f"revenue-{summary.start_date}-{summary.end_date}-{summary.group_by}.csv"
    return PlainTextResponse(
        content=body,
        headers={
            "Content-Type": "text/csv; charset=utf-8",
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )
