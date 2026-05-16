"""API version 1 routes."""
from fastapi import APIRouter

from app.api.v1.admin_analytics import router as admin_analytics_router
from app.api.v1.admin_broadcasts import router as admin_broadcasts_router
from app.api.v1.admin_content import router as admin_content_router
from app.api.v1.admin_pricing import router as admin_pricing_router
from app.api.v1.admin_system import router as admin_system_router
from app.api.v1.admin_users import router as admin_users_router
from app.api.v1.auth import router as auth_router
from app.api.v1.bot import router as bot_router
from app.api.v1.compliance import router as compliance_router
from app.api.v1.generate import router as generate_router
from app.api.v1.health import router as health_router
from app.api.v1.legal import router as legal_router
from app.api.v1.payment import router as payment_router
from app.api.v1.user import router as user_router

router = APIRouter()
router.include_router(health_router)
router.include_router(auth_router)
router.include_router(bot_router)
router.include_router(legal_router)
router.include_router(user_router)
router.include_router(compliance_router)
router.include_router(payment_router)
router.include_router(generate_router)
router.include_router(admin_users_router)
router.include_router(admin_pricing_router)
router.include_router(admin_analytics_router)
router.include_router(admin_broadcasts_router)
router.include_router(admin_content_router)
router.include_router(admin_system_router)

__all__ = ["router"]
