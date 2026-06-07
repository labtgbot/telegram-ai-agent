"""FastAPI dependency providers for auth.

* :func:`get_current_admin` — extract a Bearer JWT, validate it, and resolve
  the admin user.  Raises ``401`` on any failure.
* :func:`get_current_user_from_init_data` — verify ``X-Telegram-Init-Data``
  and either create or update the user record.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import InvalidTokenError, TokenExpiredError, decode_token
from app.auth.rbac import Role, role_satisfies
from app.auth.telegram import (
    InitDataExpiredError,
    InitDataInvalidError,
    verify_init_data,
)
from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.models.user import User
from app.services.users import find_user_by_id, upsert_telegram_user


def _settings_dep() -> Settings:
    return get_settings()


SettingsDep = Annotated[Settings, Depends(_settings_dep)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _extract_bearer(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing_authorization",
            headers={"WWW-Authenticate": "Bearer"},
        )
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_authorization_scheme",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return parts[1]


async def get_current_admin(
    settings: SettingsDep,
    session: SessionDep,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """Resolve the authenticated admin from a Bearer access token.

    Raises:
        HTTPException(401): missing/invalid/expired token, unknown user.
        HTTPException(403): user is banned or no longer holds an admin role.
    """
    token = _extract_bearer(authorization)
    try:
        claims = decode_token(
            token,
            secret=settings.admin_jwt_secret,
            algorithm=settings.admin_jwt_algorithm,
            expected_type="access",
        )
    except TokenExpiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token_expired",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        ) from exc
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_token",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        ) from exc

    try:
        user_id = int(claims.sub)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_token",
        ) from exc

    user = await find_user_by_id(session, user_id)
    if user is None or user.is_banned:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="user_not_found_or_banned",
        )
    actual = Role.coerce(user.role)
    if not role_satisfies(actual, Role.ANALYST):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="not_an_admin",
        )
    return user


async def get_current_user_from_init_data(
    request: Request,
    settings: SettingsDep,
    session: SessionDep,
    x_telegram_init_data: Annotated[str | None, Header()] = None,
) -> User:
    """Verify ``X-Telegram-Init-Data`` and return the upserted user.

    Falls back to ``request.query_params["initData"]`` so the same dependency
    works for endpoints used by mini-apps that pass the value in the URL.
    """
    raw = x_telegram_init_data or request.query_params.get("initData")
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing_init_data",
        )
    try:
        payload = verify_init_data(
            raw,
            bot_token=settings.telegram_bot_token,
            max_age_seconds=settings.telegram_init_data_max_age,
        )
    except InitDataExpiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="init_data_expired",
        ) from exc
    except InitDataInvalidError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_init_data",
        ) from exc

    user_payload = payload.get("user")
    if not isinstance(user_payload, dict):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="init_data_missing_user",
        )

    user, _created = await upsert_telegram_user(
        session,
        telegram_user=user_payload,
        super_admin_ids=settings.super_admin_ids,
    )
    if user.is_banned:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="user_banned",
        )
    request.state.user = user
    request.state.user_id = user.id
    return user
