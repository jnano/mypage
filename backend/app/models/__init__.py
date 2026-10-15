"""ORM 모델 — 설계도 §4 와 일대일. 표에 없는 칸은 만들지 않는다(tests/test_schema_contract.py)."""

from app.models.boards import (
    Board,
    BoardAccess,
    BoardCategory,
    BoardDailyStat,
    BoardGroup,
    BoardModerator,
    BoardSlugHistory,
    BoardSubscription,
)
from app.models.comments import Attachment, Comment
from app.models.members import Member, MemberGroup, MemberGroupMember, SiteSetting
from app.models.moderation import MemberSanction, ModerationLog, Report
from app.models.notifications import Notification, NotificationPref
from app.models.posts import (
    Post,
    PostCategory,
    PostReaction,
    PostRelation,
    PostScrap,
    PostSearch,
    PostStat,
    PostTombstone,
    PostViewDaily,
    PostViewOnce,
)
from app.models.system import (
    IdempotencyKey,
    OutboxEvent,
    RateLimitCounter,
    SearchSynonym,
    SearchTerm,
    WorkerSchedule,
)

__all__ = [
    "Attachment",
    "Board",
    "BoardAccess",
    "BoardCategory",
    "BoardDailyStat",
    "BoardGroup",
    "BoardModerator",
    "BoardSlugHistory",
    "BoardSubscription",
    "Comment",
    "IdempotencyKey",
    "Member",
    "MemberGroup",
    "MemberGroupMember",
    "MemberSanction",
    "ModerationLog",
    "Notification",
    "NotificationPref",
    "OutboxEvent",
    "Post",
    "PostCategory",
    "PostReaction",
    "PostRelation",
    "PostScrap",
    "PostSearch",
    "PostStat",
    "PostTombstone",
    "PostViewDaily",
    "PostViewOnce",
    "RateLimitCounter",
    "Report",
    "SearchSynonym",
    "SearchTerm",
    "SiteSetting",
    "WorkerSchedule",
]
