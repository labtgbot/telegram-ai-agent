"""API version 1 routes."""
from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.bot import router as bot_router
from app.api.v1.health import router as health_router

router = APIRouter()
router.include_router(health_router)
router.include_router(auth_router)
router.include_router(bot_router)

__all__ = ["router"]
