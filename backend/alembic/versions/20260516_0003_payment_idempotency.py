"""payments: enforce idempotency on transactions.payment_id

Revision ID: 0003_payment_idempotency
Revises: 0002_auth_user_columns
Create Date: 2026-05-16

Phase 2 introduces Telegram Stars purchases.  Idempotency for the
``successful_payment`` webhook is keyed by ``telegram_payment_charge_id``
embedded into ``transactions.payment_id`` (prefixed with ``tg:``).  This
migration adds:

* A partial unique index on ``payment_id`` that excludes ``NULL`` so
  legacy/manual rows without a payment ID stay valid, but two purchase
  rows with the same ``tg:<charge_id>`` (or ``invoice:<payload>``)
  cannot coexist.  This is the database-level safety net behind
  :class:`app.services.payments.PaymentService.finalize_successful_payment`.

* A regular index on ``payment_status`` so the pending-invoice lookup
  (``WHERE payment_id = 'invoice:...' AND payment_status = 'pending'``)
  stays cheap as the table grows.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_payment_idempotency"
down_revision: str | Sequence[str] | None = "0002_auth_user_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_transactions_payment_id",
        "transactions",
        ["payment_id"],
        unique=True,
        postgresql_where=sa.text("payment_id IS NOT NULL"),
    )
    op.create_index(
        "ix_transactions_payment_status",
        "transactions",
        ["payment_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_transactions_payment_status", table_name="transactions")
    op.drop_index("uq_transactions_payment_id", table_name="transactions")
