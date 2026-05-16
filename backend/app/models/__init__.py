"""SQLAlchemy ORM models.

Importing this package registers every table on the shared ``Base.metadata``,
which is what Alembic introspects in ``env.py``.
"""
from app.models.admin_setting import AdminSetting
from app.models.base import Base
from app.models.chat_history import ChatMessage, ChatThread
from app.models.daily_analytics import DailyAnalytics
from app.models.daily_bonus_claim import DailyBonusClaim
from app.models.subscription import Subscription
from app.models.token_usage_log import TokenUsageLog
from app.models.transaction import Transaction
from app.models.user import User
from app.models.video_job import VideoJob

__all__ = [
    "AdminSetting",
    "Base",
    "ChatMessage",
    "ChatThread",
    "DailyAnalytics",
    "DailyBonusClaim",
    "Subscription",
    "TokenUsageLog",
    "Transaction",
    "User",
    "VideoJob",
]
