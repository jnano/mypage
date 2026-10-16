"""알림 — 설계도 §4.5, §7"""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models._columns import ONE, TRUE, created_at, pk_id, updated_at


class Notification(Base):
    """dedupe_key 는 재처리 방지, group_key 는 안 읽은 알림 묶음(UPSERT)."""

    __tablename__ = "notifications"

    id: Mapped[int] = pk_id()
    recipient_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("members.id", ondelete="CASCADE")
    )
    type: Mapped[str] = mapped_column(String(30))
    actor_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("members.id", ondelete="SET NULL")
    )
    actor_count: Mapped[int] = mapped_column(Integer, server_default=ONE)
    post_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("posts.id", ondelete="SET NULL")
    )
    comment_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("comments.id", ondelete="SET NULL")
    )
    title_snapshot: Mapped[str] = mapped_column(String(300))
    group_key: Mapped[str] = mapped_column(String(100))
    dedupe_key: Mapped[str] = mapped_column(String(100), unique=True)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


Index("ix_notifications_recipient", Notification.recipient_id, Notification.created_at.desc())
# 글·댓글 영구 삭제의 SET NULL 이 찾는 칸 — 알림은 가장 빨리 커지는 표(3단계 측정 §4.7)
Index("ix_notifications_post", Notification.post_id, postgresql_where=text("post_id IS NOT NULL"))
Index("ix_notifications_comment", Notification.comment_id, postgresql_where=text("comment_id IS NOT NULL"))
Index(
    "ix_notifications_unread",
    Notification.recipient_id,
    postgresql_where=text("read_at IS NULL"),
)
Index(
    "uq_notifications_group_unread",
    Notification.recipient_id,
    Notification.group_key,
    unique=True,
    postgresql_where=text("read_at IS NULL"),
)


class NotificationPref(Base):
    __tablename__ = "notification_prefs"

    member_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("members.id", ondelete="CASCADE"), primary_key=True
    )
    type: Mapped[str] = mapped_column(String(30), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=TRUE)
