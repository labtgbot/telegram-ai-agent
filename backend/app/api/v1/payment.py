"""Payment endpoints (Telegram Stars).

* ``POST /api/v1/payment/create-invoice`` — Mini App requests a fresh
  Stars invoice link for a package.  Returns ``telegram_invoice_link``
  which the client opens with ``Telegram.WebApp.openInvoice``.
* ``GET  /api/v1/payment/status/{invoice_id}`` — poll endpoint used by
  the Mini App while waiting for the ``successful_payment`` webhook.

Both endpoints require ``X-Telegram-Init-Data`` (the same dependency the
balance + history endpoints use), so the caller is always identified.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.v1.bot import BotClientDep
from app.auth.dependencies import SessionDep, get_current_user_from_init_data
from app.bot.client import TelegramApiError
from app.core.logging import get_logger
from app.models.user import User
from app.services.payments import (
    InvoiceNotFoundError,
    InvoicePayloadInvalidError,
    PackageNotFoundError,
    PaymentService,
)

router = APIRouter(prefix="/payment", tags=["payment"])
logger = get_logger(__name__)


class CreateInvoiceRequest(BaseModel):
    package: str = Field(..., min_length=1, max_length=64)


class CreateInvoiceResponse(BaseModel):
    invoice_id: str
    stars_amount: int
    tokens_amount: int
    telegram_invoice_link: str
    transaction_id: int
    is_subscription: bool = False


class PaymentStatusResponse(BaseModel):
    invoice_id: str
    status: str
    package: str | None = None
    tokens_credited: int = 0
    stars_amount: int | None = None
    transaction_id: int
    created_at: datetime
    completed_at: datetime | None = None
    telegram_payment_charge_id: str | None = None


@router.post(
    "/create-invoice",
    response_model=CreateInvoiceResponse,
    summary="Create a Telegram Stars invoice link for a token package",
)
async def create_invoice(
    body: CreateInvoiceRequest,
    session: SessionDep,
    client: BotClientDep,
    user: Annotated[User, Depends(get_current_user_from_init_data)],
) -> CreateInvoiceResponse:
    service = PaymentService(session, client=client)
    try:
        invoice = await service.create_invoice(
            user_id=user.id,
            package_code=body.package,
        )
    except PackageNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="package_not_found",
        ) from exc
    except TelegramApiError as exc:
        logger.warning(
            "payment.create_invoice.telegram_error",
            user_id=user.id,
            package=body.package,
            error=str(exc),
        )
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="telegram_api_error",
        ) from exc

    try:
        await session.commit()
    except Exception as exc:  # noqa: BLE001 — surface a clean 500
        await session.rollback()
        logger.exception(
            "payment.create_invoice.commit_failed", error=str(exc)
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="commit_failed",
        ) from exc

    return CreateInvoiceResponse(
        invoice_id=invoice.invoice_id,
        stars_amount=invoice.stars_amount,
        tokens_amount=invoice.tokens_amount,
        telegram_invoice_link=invoice.telegram_invoice_link,
        transaction_id=invoice.transaction_id,
        is_subscription=invoice.is_subscription,
    )


@router.get(
    "/status/{invoice_id}",
    response_model=PaymentStatusResponse,
    summary="Lookup the status of an invoice owned by the calling user",
)
async def get_invoice_status(
    invoice_id: str,
    session: SessionDep,
    user: Annotated[User, Depends(get_current_user_from_init_data)],
) -> PaymentStatusResponse:
    service = PaymentService(session)
    try:
        snapshot = await service.get_status(invoice_id=invoice_id, user_id=user.id)
    except (InvoiceNotFoundError, InvoicePayloadInvalidError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="invoice_not_found",
        ) from exc
    return PaymentStatusResponse(
        invoice_id=snapshot.invoice_id,
        status=snapshot.status,
        package=snapshot.package_code,
        tokens_credited=(
            snapshot.tokens_credited if snapshot.status == "completed" else 0
        ),
        stars_amount=snapshot.stars_amount,
        transaction_id=snapshot.transaction_id,
        created_at=snapshot.created_at,
        completed_at=snapshot.completed_at,
        telegram_payment_charge_id=snapshot.telegram_payment_charge_id,
    )
