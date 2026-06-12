"""SQLAlchemy ORM models.

Importing this package registers every table on the shared ``Base.metadata``,
which is what Alembic introspects in ``env.py``.
"""

from app.models.account_deletion import AccountDeletionRequest
from app.models.admin_audit_log import AdminAuditLog
from app.models.admin_refresh_session import AdminRefreshSession
from app.models.admin_setting import AdminSetting
from app.models.base import Base
from app.models.broadcast import Broadcast, BroadcastRecipient
from app.models.chat_history import ChatMessage, ChatThread
from app.models.daily_analytics import DailyAnalytics
from app.models.daily_bonus_claim import DailyBonusClaim
from app.models.faq_item import FaqItem
from app.models.prompt_template import PromptTemplate
from app.models.subscription import Subscription
from app.models.token_usage_log import TokenUsageLog
from app.models.transaction import Transaction
from app.models.user import User
from app.models.video_job import VideoJob
from app.models.welcome_message import WelcomeMessage

__all__ = [
    "AccountDeletionRequest",
    "AdminAuditLog",
    "AdminRefreshSession",
    "AdminSetting",
    "Base",
    "Broadcast",
    "BroadcastRecipient",
    "ChatMessage",
    "ChatThread",
    "DailyAnalytics",
    "DailyBonusClaim",
    "FaqItem",
    "PromptTemplate",
    "Subscription",
    "TokenUsageLog",
    "Transaction",
    "User",
    "VideoJob",
    "WelcomeMessage",
]
