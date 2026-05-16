"""Compliance endpoints — Phase-4 stubs.

Currently exposes the **age-verification** flow described in
:doc:`docs/legal/AGE_VERIFICATION.md`. The provider integration (Telegram
Passport / Veriff / Yoti) is deliberately out of scope: this module ships
the route shape, the feature flag, and a development-only
``self_declared`` path so the Mini App can be wired up against a working
contract.

Routes:

* ``GET  /api/v1/user/me/age-verification`` — current state for the user.
* ``POST /api/v1/user/me/age-verification`` — submit a verification proof.

Both routes are 404 when the feature flag is off (``compliance_age_gate
_enabled = false``). When enabled with a non-``self_declared`` provider,
``POST`` returns 501 until the provider client is implemented — never
**accept** an unverified payload in production.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth.dependencies import get_current_user_from_init_data
from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.models.user import User

router = APIRouter(prefix="/user/me", tags=["compliance"])
logger = get_logger(__name__)

#: Providers we accept on ``POST``. ``self_declared`` is dev-only.
_KNOWN_PROVIDERS: frozenset[str] = frozenset(
    {"self_declared", "telegram_passport", "veriff", "yoti"}
)

#: Providers that have a real backend integration. Anything outside this
#: set returns 501 from ``POST`` even when the feature flag is on, so we
#: cannot accidentally accept an unverified self-declaration in prod.
_IMPLEMENTED_PROVIDERS: frozenset[str] = frozenset({"self_declared"})


class AgeVerificationStatus(BaseModel):
    """Read-side view returned by ``GET /user/me/age-verification``."""

    enabled: bool = Field(
        description="Whether the age-gate flow is currently exposed."
    )
    provider: str = Field(
        description="Provider configured to verify proofs."
    )
    verified: bool = Field(
        default=False,
        description=(
            "Whether the user has cleared the gate. Always false in the "
            "Phase-4 stub — provider integration is not yet wired up."
        ),
    )
    verified_at: datetime | None = Field(
        default=None,
        description="Timestamp of the last successful verification, if any.",
    )


class AgeVerificationSubmission(BaseModel):
    """Body for ``POST /user/me/age-verification``.

    The minimal contract accepted today is ``confirmed_18_plus: true``
    under the ``self_declared`` provider; richer providers will add their
    own typed payloads (e.g. Telegram Passport encrypted data) in a
    follow-up.
    """

    confirmed_18_plus: bool = Field(
        description="User-supplied confirmation that they are 18 or older."
    )
    provider: Literal[
        "self_declared", "telegram_passport", "veriff", "yoti"
    ] | None = Field(
        default=None,
        description=(
            "Optional override for the verification provider. Must match "
            "the server-side configured provider when supplied."
        ),
    )


def _ensure_enabled(settings: Settings) -> None:
    """Raise 404 when the feature flag is off — keeps the surface invisible."""
    if not settings.compliance_age_gate_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="age_verification_disabled",
        )


def _resolve_provider(settings: Settings, override: str | None) -> str:
    provider = (override or settings.compliance_age_gate_provider or "").strip()
    if provider not in _KNOWN_PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="age_verification_provider_unknown",
        )
    if override and override != settings.compliance_age_gate_provider:
        # Reject silent provider switching from the client — config rules.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="age_verification_provider_mismatch",
        )
    return provider


@router.get(
    "/age-verification",
    response_model=AgeVerificationStatus,
    summary="Current age-verification state for the caller",
)
async def get_age_verification(
    user: Annotated[User, Depends(get_current_user_from_init_data)],
) -> AgeVerificationStatus:
    settings = get_settings()
    _ensure_enabled(settings)
    # Stateless stub: until a provider is wired up, the answer is always
    # "not verified" — see docs/legal/AGE_VERIFICATION.md.
    logger.info("compliance.age_verification.read", user_id=user.id)
    return AgeVerificationStatus(
        enabled=True,
        provider=settings.compliance_age_gate_provider,
        verified=False,
        verified_at=None,
    )


@router.post(
    "/age-verification",
    response_model=AgeVerificationStatus,
    summary="Submit an age-verification proof",
)
async def submit_age_verification(
    payload: AgeVerificationSubmission,
    user: Annotated[User, Depends(get_current_user_from_init_data)],
) -> AgeVerificationStatus:
    settings = get_settings()
    _ensure_enabled(settings)
    provider = _resolve_provider(settings, payload.provider)

    if provider not in _IMPLEMENTED_PROVIDERS:
        # We accept POSTs to discover the contract but refuse to mark the
        # user as verified — preventing a "production self-declaration"
        # foot-gun.
        logger.info(
            "compliance.age_verification.provider_not_integrated",
            user_id=user.id,
            provider=provider,
        )
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="age_verification_provider_not_integrated",
        )

    # ``self_declared`` is development-only — guard against accidental
    # production exposure via the dev-flag on settings.
    if provider == "self_declared" and not settings.is_development:
        logger.warning(
            "compliance.age_verification.self_declared_blocked",
            user_id=user.id,
            app_env=settings.app_env,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="age_verification_self_declared_not_allowed",
        )

    if not payload.confirmed_18_plus:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="age_verification_declined",
        )

    now = datetime.now(UTC)
    # Phase-4 stub: we *acknowledge* the declaration but do not persist
    # ``age_verified_at`` because no 18+ feature consumes it yet. The
    # column + audit log entry will be added with the first real provider
    # (see AGE_VERIFICATION.md > Implementation status).
    logger.info(
        "compliance.age_verification.accepted",
        user_id=user.id,
        provider=provider,
    )
    return AgeVerificationStatus(
        enabled=True,
        provider=provider,
        verified=True,
        verified_at=now,
    )
