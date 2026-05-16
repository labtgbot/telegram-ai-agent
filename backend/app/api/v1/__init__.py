"""API version 1 routes."""
from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.bot import router as bot_router
from app.api.v1.generate import router as generate_router
from app.api.v1.health import router as health_router
from app.api.v1.payment import router as payment_router
from app.api.v1.user import router as user_router

router = APIRouter()
router.include_router(health_router)
router.include_router(auth_router)
router.include_router(bot_router)
router.include_router(user_router)
router.include_router(payment_router)
router.include_router(generate_router)

__all__ = ["router"]
