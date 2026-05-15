"""Phase 1 authentication endpoints.

* ``POST /auth/telegram/verify`` — validate WebApp ``initData`` and
  create-or-update the corresponding user record.
* ``POST /auth/admin/login/request`` — request a one-time login code.
* ``POST /auth/admin/login/verify`` — exchange code (+ optional TOTP) for
  access and refresh tokens.
* ``POST /auth/admin/refresh`` — rotate access token using a refresh token.
* ``GET  /auth/admin/me`` — sanity-check the current admin's identity.
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import (
    SessionDep,
    SettingsDep,
    get_current_admin,
    get_current_user_from_init_data,
)
from app.auth.jwt import (
    InvalidTokenError,
    TokenExpiredError,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.auth.rbac import Role, role_satisfies
from app.auth.totp import verify_totp
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.models.user import User
from app.services.admin_login import (
    LoginCodeAttemptsExceededError,
    LoginCodeInvalidError,
    LoginCodeMissingError,
    request_admin_login,
    verify_admin_login,
)
from app.services.users import (
    find_user_by_telegram_id,
    record_admin_login,
)

router = APIRouter(prefix="/auth", tags=["auth"])
logger = get_logger(__name__)


def _redis_dep() -> Redis:
    return get_redis()


RedisDep = Annotated[Redis, Depends(_redis_dep)]


# ---------------------------------------------------------------------- types

class UserPublic(BaseModel):
    id: int
    telegram_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    language_code: str | None
    role: str
    referral_code: str
    is_premium: bool
    is_banned: bool

    @classmethod
    def from_orm_user(cls, user: User) -> UserPublic:
        return cls(
            id=user.id,
            telegram_id=user.telegram_id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            language_code=user.language_code,
            role=user.role,
            referral_code=user.referral_code,
            is_premium=user.is_premium,
            is_banned=user.is_banned,
        )


class TelegramVerifyResponse(BaseModel):
    user: UserPublic


class AdminLoginRequest(BaseModel):
    telegram_id: int = Field(..., description="Telegram user id of the admin.")


class AdminLoginRequestResponse(BaseModel):
    delivery: str = Field(
        ...,
        description="Where the code was delivered: 'bot' in prod, 'response' in dev.",
    )
    ttl_seconds: int
    code: str | None = Field(
        default=None,
        description="The OTP itself — only returned in development mode.",
    )


class AdminLoginVerifyRequest(BaseModel):
    telegram_id: int
    code: str = Field(..., min_length=4, max_length=10)
    totp_code: str | None = Field(default=None, max_length=10)


class TokenPairResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int


class AdminRefreshRequest(BaseModel):
    refresh_token: str


class AdminMeResponse(BaseModel):
    user: UserPublic


# --------------------------------------------------------------- /telegram/verify

@router.post(
    "/telegram/verify",
    response_model=TelegramVerifyResponse,
    summary="Verify Telegram WebApp initData",
)
async def telegram_verify(
    user: Annotated[User, Depends(get_current_user_from_init_data)],
) -> TelegramVerifyResponse:
    """Validate ``initData`` and return the up-to-date user record.

    The user row is created on first contact and refreshed on every call.
    """
    return TelegramVerifyResponse(user=UserPublic.from_orm_user(user))


# ------------------------------------------------------------- /admin/login/...

async def _require_admin_candidate(
    session: AsyncSession, telegram_id: int
) -> User:
    user = await find_user_by_telegram_id(session, telegram_id)
    if user is None or user.is_banned:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="not_an_admin",
        )
    if not role_satisfies(Role.coerce(user.role), Role.ANALYST):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="not_an_admin",
        )
    return user


@router.post(
    "/admin/login/request",
    response_model=AdminLoginRequestResponse,
    summary="Issue a one-time admin login code",
)
async def admin_login_request(
    payload: AdminLoginRequest,
    settings: SettingsDep,
    session: SessionDep,
    redis: RedisDep,
) -> AdminLoginRequestResponse:
    user = await _require_admin_candidate(session, payload.telegram_id)
    login = await request_admin_login(
        redis,
        telegram_id=user.telegram_id,
        secret=settings.admin_jwt_secret,
        ttl_seconds=settings.admin_login_code_ttl,
        code_length=settings.admin_login_code_length,
    )
    logger.info(
        "auth.admin.login.requested",
        telegram_id=user.telegram_id,
        ttl=login.ttl_seconds,
    )
    expose_code = settings.app_debug or settings.is_development
    return AdminLoginRequestResponse(
        delivery="response" if expose_code else "bot",
        ttl_seconds=login.ttl_seconds,
        code=login.code if expose_code else None,
    )


@router.post(
    "/admin/login/verify",
    response_model=TokenPairResponse,
    summary="Exchange a one-time code (+ optional TOTP) for JWTs",
)
async def admin_login_verify(
    payload: AdminLoginVerifyRequest,
    settings: SettingsDep,
    session: SessionDep,
    redis: RedisDep,
) -> TokenPairResponse:
    user = await _require_admin_candidate(session, payload.telegram_id)

    try:
        await verify_admin_login(
            redis,
            telegram_id=user.telegram_id,
            code=payload.code,
            secret=settings.admin_jwt_secret,
            max_attempts=settings.admin_login_max_attempts,
            ttl_seconds=settings.admin_login_code_ttl,
        )
    except LoginCodeMissingError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="login_code_missing",
        ) from exc
    except LoginCodeAttemptsExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="login_attempts_exceeded",
        ) from exc
    except LoginCodeInvalidError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="login_code_invalid",
        ) from exc

    actual_role = Role.coerce(user.role)
    if actual_role is Role.SUPER_ADMIN and user.totp_enabled:
        if not payload.totp_code or not user.totp_secret:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="totp_required",
            )
        if not verify_totp(user.totp_secret, payload.totp_code):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="totp_invalid",
            )

    await record_admin_login(session, user)

    return _mint_token_pair(user, settings)


@router.post(
    "/admin/refresh",
    response_model=TokenPairResponse,
    summary="Rotate access token using a refresh token",
)
async def admin_refresh(
    payload: AdminRefreshRequest,
    settings: SettingsDep,
    session: SessionDep,
) -> TokenPairResponse:
    try:
        claims = decode_token(
            payload.refresh_token,
            secret=settings.admin_jwt_secret,
            algorithm=settings.admin_jwt_algorithm,
            expected_type="refresh",
        )
    except TokenExpiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="refresh_token_expired",
        ) from exc
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_refresh_token",
        ) from exc

    try:
        user_id = int(claims.sub)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_refresh_token",
        ) from exc

    from app.services.users import find_user_by_id

    user = await find_user_by_id(session, user_id)
    if user is None or user.is_banned:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="user_not_found_or_banned",
        )
    if not role_satisfies(Role.coerce(user.role), Role.ANALYST):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="not_an_admin",
        )
    return _mint_token_pair(user, settings)


@router.get(
    "/admin/me",
    response_model=AdminMeResponse,
    summary="Return the current admin's profile",
)
async def admin_me(
    admin: Annotated[User, Depends(get_current_admin)],
) -> AdminMeResponse:
    return AdminMeResponse(user=UserPublic.from_orm_user(admin))


# ---------------------------------------------------------------- helpers


def _mint_token_pair(user: User, settings: Any) -> TokenPairResponse:
    access = create_access_token(
        subject=user.id,
        role=user.role,
        secret=settings.admin_jwt_secret,
        algorithm=settings.admin_jwt_algorithm,
        ttl_seconds=settings.admin_access_token_ttl,
    )
    refresh = create_refresh_token(
        subject=user.id,
        role=user.role,
        secret=settings.admin_jwt_secret,
        algorithm=settings.admin_jwt_algorithm,
        ttl_seconds=settings.admin_refresh_token_ttl,
    )
    return TokenPairResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.admin_access_token_ttl,
    )
