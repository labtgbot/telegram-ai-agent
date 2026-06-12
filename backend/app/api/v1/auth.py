"""Phase 1 authentication endpoints.

* ``POST /auth/telegram/verify`` — validate WebApp ``initData`` and
  create-or-update the corresponding user record.
* ``POST /auth/admin/login/request`` — request a one-time login code.
* ``POST /auth/admin/login/verify`` — exchange code (+ optional TOTP) for
  access and refresh tokens.
* ``POST /auth/admin/refresh`` — rotate access token using a refresh token.
* ``POST /auth/admin/logout`` — revoke a refresh token server-side.
* ``GET  /auth/admin/me`` — sanity-check the current admin's identity.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.rate_limit import RateLimiterDep
from app.auth.dependencies import (
    SessionDep,
    SettingsDep,
    get_current_admin,
    get_current_user_from_init_data,
)
from app.auth.jwt import (
    InvalidTokenError,
    TokenClaims,
    TokenExpiredError,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.auth.rbac import Role, role_satisfies
from app.auth.totp import verify_totp_timecode
from app.core.client_ip import resolve_client_ip
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.models.user import User
from app.services.admin_login import (
    LoginCodeAttemptsExceededError,
    LoginCodeInvalidError,
    LoginCodeMissingError,
    generate_numeric_login_code,
    request_admin_login,
    verify_admin_login,
)
from app.services.admin_refresh_sessions import (
    RefreshSessionExpiredError,
    RefreshSessionReusedError,
    RefreshSessionRevokedError,
    RefreshSessionUnknownError,
    RefreshSessionUserMismatchError,
    create_refresh_session,
    revoke_refresh_session,
    rotate_refresh_session,
)
from app.services.rate_limit_config import (
    ACTION_ADMIN_LOGIN_REQUEST,
    ACTION_ADMIN_LOGIN_VERIFY,
    PLAN_ADMIN_LOGIN,
)
from app.services.rate_limiter import RateLimitedError
from app.services.users import (
    find_user_by_telegram_id,
    mark_totp_timecode_used,
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


class AdminLogoutRequest(BaseModel):
    refresh_token: str


class AdminLogoutResponse(BaseModel):
    status: str = "ok"


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


async def _find_admin_candidate(session: AsyncSession, telegram_id: int) -> User | None:
    user = await find_user_by_telegram_id(session, telegram_id)
    if user is None or user.is_banned:
        return None
    if not role_satisfies(Role.coerce(user.role), Role.ANALYST):
        return None
    return user


async def _require_admin_candidate(session: AsyncSession, telegram_id: int) -> User:
    user = await _find_admin_candidate(session, telegram_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="not_an_admin",
        )
    return user


def _admin_login_exposes_code(settings: Any) -> bool:
    return bool(settings.app_debug or settings.is_development)


def _admin_login_request_response(
    settings: Any,
    *,
    ttl_seconds: int,
    code: str | None,
) -> AdminLoginRequestResponse:
    expose_code = _admin_login_exposes_code(settings)
    return AdminLoginRequestResponse(
        delivery="response" if expose_code else "bot",
        ttl_seconds=ttl_seconds,
        code=code if expose_code else None,
    )


def _admin_login_rate_limit_identifiers(request: Request, telegram_id: int) -> tuple[str, str]:
    client_ip = resolve_client_ip(request) or "unknown"
    return (f"ip:{client_ip}", f"telegram_id:{telegram_id}")


async def _enforce_admin_login_rate_limit(
    *,
    request: Request,
    limiter: RateLimiterDep,
    telegram_id: int,
    action: str,
) -> None:
    for identifier in _admin_login_rate_limit_identifiers(request, telegram_id):
        try:
            await limiter.consume(
                plan=PLAN_ADMIN_LOGIN,
                identifier=identifier,
                action=action,
            )
        except RateLimitedError as exc:
            headers = {
                "Retry-After": str(exc.retry_after),
                "X-RateLimit-Limit": str(exc.limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(exc.reset_after),
                "X-RateLimit-Quota": exc.quota_key,
            }
            logger.info(
                "auth.admin.login.rate_limited",
                action=action,
                identifier=identifier,
                quota=exc.quota_key,
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "rate_limited",
                    "plan": PLAN_ADMIN_LOGIN,
                    "action": action,
                    "quota": exc.quota_key,
                    "limit": exc.limit,
                    "retry_after": exc.retry_after,
                },
                headers=headers,
            ) from exc


@router.post(
    "/admin/login/request",
    response_model=AdminLoginRequestResponse,
    summary="Issue a one-time admin login code",
)
async def admin_login_request(
    request: Request,
    payload: AdminLoginRequest,
    settings: SettingsDep,
    session: SessionDep,
    redis: RedisDep,
    limiter: RateLimiterDep,
) -> AdminLoginRequestResponse:
    await _enforce_admin_login_rate_limit(
        request=request,
        limiter=limiter,
        telegram_id=payload.telegram_id,
        action=ACTION_ADMIN_LOGIN_REQUEST,
    )
    user = await _find_admin_candidate(session, payload.telegram_id)
    if user is None:
        logger.info(
            "auth.admin.login.requested",
            telegram_id=payload.telegram_id,
            accepted=False,
        )
        return _admin_login_request_response(
            settings,
            ttl_seconds=settings.admin_login_code_ttl,
            code=generate_numeric_login_code(settings.admin_login_code_length),
        )

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
        accepted=True,
    )
    return _admin_login_request_response(
        settings,
        ttl_seconds=login.ttl_seconds,
        code=login.code,
    )


@router.post(
    "/admin/login/verify",
    response_model=TokenPairResponse,
    summary="Exchange a one-time code (+ optional TOTP) for JWTs",
)
async def admin_login_verify(
    request: Request,
    payload: AdminLoginVerifyRequest,
    settings: SettingsDep,
    session: SessionDep,
    redis: RedisDep,
    limiter: RateLimiterDep,
) -> TokenPairResponse:
    await _enforce_admin_login_rate_limit(
        request=request,
        limiter=limiter,
        telegram_id=payload.telegram_id,
        action=ACTION_ADMIN_LOGIN_VERIFY,
    )
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
        timecode = verify_totp_timecode(user.totp_secret, payload.totp_code)
        if timecode is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="totp_invalid",
            )
        if not await mark_totp_timecode_used(session, user, timecode):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="totp_invalid",
            )

    await record_admin_login(session, user)
    token_pair, refresh_claims = _mint_token_pair(user, settings)
    await create_refresh_session(
        session,
        claims=refresh_claims,
        user=user,
        secret=settings.admin_jwt_secret,
    )
    await session.commit()

    return token_pair


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
    token_pair, next_refresh_claims = _mint_token_pair(user, settings)
    try:
        await rotate_refresh_session(
            session,
            current_claims=claims,
            next_claims=next_refresh_claims,
            user=user,
            secret=settings.admin_jwt_secret,
        )
    except RefreshSessionExpiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="refresh_token_expired",
        ) from exc
    except RefreshSessionReusedError as exc:
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="refresh_token_reused",
        ) from exc
    except RefreshSessionRevokedError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="refresh_token_revoked",
        ) from exc
    except (RefreshSessionUnknownError, RefreshSessionUserMismatchError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_refresh_token",
        ) from exc

    await session.commit()
    return token_pair


@router.post(
    "/admin/logout",
    response_model=AdminLogoutResponse,
    summary="Revoke an admin refresh token",
)
async def admin_logout(
    payload: AdminLogoutRequest,
    settings: SettingsDep,
    session: SessionDep,
) -> AdminLogoutResponse:
    try:
        claims = decode_token(
            payload.refresh_token,
            secret=settings.admin_jwt_secret,
            algorithm=settings.admin_jwt_algorithm,
            expected_type="refresh",
        )
    except (TokenExpiredError, InvalidTokenError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_refresh_token",
        ) from exc

    try:
        await revoke_refresh_session(
            session,
            claims=claims,
            secret=settings.admin_jwt_secret,
            reason="logout",
        )
    except RefreshSessionReusedError as exc:
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="refresh_token_reused",
        ) from exc

    await session.commit()
    return AdminLogoutResponse()


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


def _mint_token_pair(user: User, settings: Any) -> tuple[TokenPairResponse, TokenClaims]:
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
    refresh_claims = decode_token(
        refresh,
        secret=settings.admin_jwt_secret,
        algorithm=settings.admin_jwt_algorithm,
        expected_type="refresh",
    )
    return (
        TokenPairResponse(
            access_token=access,
            refresh_token=refresh,
            expires_in=settings.admin_access_token_ttl,
        ),
        refresh_claims,
    )
