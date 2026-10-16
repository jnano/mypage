"""게시판 — 설계도 §4.2"""

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models._columns import (
    FALSE,
    ONE,
    TRUE,
    ZERO,
    created_at,
    enum_check,
    lit,
    pk_id,
    range_check,
    updated_at,
)
from app.models.enums import (
    ACCESS_SUBJECT_TYPES,
    BOARD_KINDS,
    EDITORS,
    HIDDEN_POST_LISTINGS,
    PINNED_DISPLAYS,
    VIEW_COUNT_MODES,
)

LEVEL_COLUMNS = (
    "list_level",
    "read_level",
    "write_level",
    "comment_level",
    "upload_level",
    "download_level",
)


class BoardGroup(Base):
    __tablename__ = "board_groups"

    id: Mapped[int] = pk_id()
    name: Mapped[str] = mapped_column(String(50))
    sort_order: Mapped[int] = mapped_column(Integer, server_default=ZERO)
    created_at: Mapped[datetime] = created_at()


class Board(Base):
    __tablename__ = "boards"
    __table_args__ = (
        enum_check("kind", BOARD_KINDS),
        enum_check("hidden_post_listing", HIDDEN_POST_LISTINGS),
        enum_check("pinned_display", PINNED_DISPLAYS),
        enum_check("view_count_mode", VIEW_COUNT_MODES),
        enum_check("editor", EDITORS),
        *(range_check(c, 0, 99) for c in LEVEL_COLUMNS),
        range_check("posts_per_page", 5, 100),
        range_check("report_auto_blind_threshold", 1),
        range_check("trash_retention_days", 1),
    )

    id: Mapped[int] = pk_id()
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(10), server_default=lit("default"))
    group_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("board_groups.id", ondelete="SET NULL")
    )
    sort_order: Mapped[int] = mapped_column(Integer, server_default=ZERO)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=TRUE)
    is_system: Mapped[bool] = mapped_column(Boolean, server_default=FALSE)
    show_in_menu: Mapped[bool] = mapped_column(Boolean, server_default=TRUE)
    list_level: Mapped[int] = mapped_column(SmallInteger, server_default=ZERO)
    read_level: Mapped[int] = mapped_column(SmallInteger, server_default=ZERO)
    write_level: Mapped[int] = mapped_column(SmallInteger, server_default=ONE)
    comment_level: Mapped[int] = mapped_column(SmallInteger, server_default=ONE)
    upload_level: Mapped[int] = mapped_column(SmallInteger, server_default=ONE)
    download_level: Mapped[int] = mapped_column(SmallInteger, server_default=ZERO)
    allow_level_lowering: Mapped[bool] = mapped_column(Boolean, server_default=FALSE)
    hidden_post_listing: Mapped[str] = mapped_column(String(8), server_default=lit("mask"))
    pinned_display: Mapped[str] = mapped_column(String(8), server_default=lit("strip"))
    allow_secret: Mapped[bool] = mapped_column(Boolean, server_default=FALSE)
    allow_comments: Mapped[bool] = mapped_column(Boolean, server_default=TRUE)
    allow_share: Mapped[bool] = mapped_column(Boolean, server_default=TRUE)
    allow_title_style: Mapped[bool] = mapped_column(Boolean, server_default=FALSE)
    protect_commented_posts: Mapped[bool] = mapped_column(Boolean, server_default=FALSE)
    view_count_mode: Mapped[str] = mapped_column(String(8), server_default=lit("daily"))
    posts_per_page: Mapped[int] = mapped_column(SmallInteger, server_default=text("20"))
    editor: Mapped[str] = mapped_column(String(10), server_default=lit("rich"))
    # JSONB 설정 칸은 DB 기본값을 두지 않는다 — 기본값은 Pydantic 모델 한 곳(§4 R5)
    upload_policy: Mapped[dict[str, Any]] = mapped_column(JSONB)
    spam_policy: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    report_auto_blind_threshold: Mapped[int | None] = mapped_column(SmallInteger)
    indexable: Mapped[bool] = mapped_column(Boolean, server_default=TRUE)
    exclude_from_search: Mapped[bool] = mapped_column(Boolean, server_default=FALSE)
    trash_retention_days: Mapped[int | None] = mapped_column(SmallInteger)
    display: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()
    # 이 게시판 화면의 틀(홈블록 §4.2). NULL = 화면 종류 board 의 틀 → 기본 틀
    layout_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("layouts.id", ondelete="SET NULL"))

    # 관계는 모두 lazy="raise" — 필요한 곳에서 selectinload/joinedload 로 명시한다(§3.1-2)
    categories: Mapped[list["BoardCategory"]] = relationship(
        back_populates="board", lazy="raise", order_by="BoardCategory.sort_order"
    )


class BoardCategory(Base):
    __tablename__ = "board_categories"
    __table_args__ = (UniqueConstraint("board_id", "name"),)

    id: Mapped[int] = pk_id()
    board_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("boards.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(50))
    sort_order: Mapped[int] = mapped_column(Integer, server_default=ZERO)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=TRUE)

    board: Mapped[Board] = relationship(back_populates="categories", lazy="raise")


class BoardAccess(Base):
    """명부 — 레벨이 모자라도 허용. subject_id 는 다형 참조라 FK 가 없다(탈퇴·그룹 삭제 때 함께 지운다)."""

    __tablename__ = "board_access"
    __table_args__ = (
        enum_check("subject_type", ACCESS_SUBJECT_TYPES),
        CheckConstraint("can_read OR can_write", name="grants_something"),
    )

    board_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("boards.id", ondelete="CASCADE"), primary_key=True
    )
    subject_type: Mapped[str] = mapped_column(String(6), primary_key=True)
    subject_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    can_read: Mapped[bool] = mapped_column(Boolean, server_default=FALSE)
    can_write: Mapped[bool] = mapped_column(Boolean, server_default=FALSE)


class BoardModerator(Base):
    __tablename__ = "board_moderators"

    board_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("boards.id", ondelete="CASCADE"), primary_key=True
    )
    member_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("members.id", ondelete="CASCADE"), primary_key=True
    )


class BoardSlugHistory(Base):
    __tablename__ = "board_slug_history"

    old_slug: Mapped[str] = mapped_column(String(100), primary_key=True)
    board_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("boards.id", ondelete="CASCADE")
    )
    changed_at: Mapped[datetime] = created_at()


class BoardSubscription(Base):
    __tablename__ = "board_subscriptions"

    board_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("boards.id", ondelete="CASCADE"), primary_key=True
    )
    member_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("members.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = created_at()


class BoardDailyStat(Base):
    __tablename__ = "board_daily_stats"

    board_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("boards.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    posts: Mapped[int] = mapped_column(Integer, server_default=ZERO)
    comments: Mapped[int] = mapped_column(Integer, server_default=ZERO)
    views: Mapped[int] = mapped_column(Integer, server_default=ZERO)
    reports: Mapped[int] = mapped_column(Integer, server_default=ZERO)
