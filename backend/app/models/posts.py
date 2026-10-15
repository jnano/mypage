"""글 — 설계도 §4.3. 인덱스는 §4.7."""

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models._columns import (
    FALSE,
    ONE,
    ZERO,
    created_at,
    enum_check,
    lit,
    pk_id,
    range_check,
    updated_at,
)
from app.models.boards import Board
from app.models.enums import (
    BLIND_SOURCES,
    CONTENT_FORMATS,
    POST_RESTORABLE_STATUSES,
    POST_STATUSES,
    POSTED_AS,
    REACTION_KINDS,
)


class Post(Base):
    __tablename__ = "posts"
    __table_args__ = (
        enum_check("content_format", CONTENT_FORMATS),
        enum_check("status", POST_STATUSES),
        enum_check("trashed_from_status", POST_RESTORABLE_STATUSES),
        enum_check("blind_source", BLIND_SOURCES),
        enum_check("posted_as", POSTED_AS),
        range_check("min_view_level", 0, 99),
        CheckConstraint(
            "(is_guest AND guest_password_hash IS NOT NULL AND member_id IS NULL)"
            " OR (NOT is_guest AND guest_password_hash IS NULL)",
            name="guest_author",
        ),
        CheckConstraint("(status = 'trashed') = (trashed_at IS NOT NULL)", name="trashed_at"),
        CheckConstraint(
            "trashed_from_status IS NULL OR status = 'trashed'", name="trashed_from"
        ),
        CheckConstraint(
            "status NOT IN ('published', 'scheduled') OR published_at IS NOT NULL",
            name="published_at",
        ),
        CheckConstraint(
            "(content_format = 'markdown') = (content_source IS NOT NULL)", name="content_source"
        ),
        CheckConstraint("pin_order IS NULL OR is_pinned", name="pin_order"),
        CheckConstraint("blind_source IS NULL OR is_blinded", name="blind_source"),
        CheckConstraint("(ip_hash IS NULL) = (ip_hash_period IS NULL)", name="ip_hash"),
    )

    id: Mapped[int] = pk_id()
    board_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("boards.id", ondelete="RESTRICT")
    )
    member_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("members.id", ondelete="SET NULL")
    )
    is_guest: Mapped[bool] = mapped_column(Boolean, server_default=FALSE)
    author_name_snapshot: Mapped[str] = mapped_column(String(50))
    guest_password_hash: Mapped[str | None] = mapped_column(String(255))
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    ip_hash_period: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(300))
    title_bold: Mapped[bool] = mapped_column(Boolean, server_default=FALSE)
    title_color: Mapped[str | None] = mapped_column(String(10))
    content_format: Mapped[str] = mapped_column(String(10))
    content_source: Mapped[str | None] = mapped_column(Text)
    content_html: Mapped[str] = mapped_column(Text)
    content_rendered: Mapped[str] = mapped_column(Text)
    sanitizer_version: Mapped[int] = mapped_column(SmallInteger)
    status: Mapped[str] = mapped_column(String(10))
    trashed_from_status: Mapped[str | None] = mapped_column(String(10))
    trashed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_pinned: Mapped[bool] = mapped_column(Boolean, server_default=FALSE)
    pin_order: Mapped[int | None] = mapped_column(SmallInteger)
    is_secret: Mapped[bool] = mapped_column(Boolean, server_default=FALSE)
    is_blinded: Mapped[bool] = mapped_column(Boolean, server_default=FALSE)
    blind_source: Mapped[str | None] = mapped_column(String(12))
    min_view_level: Mapped[int | None] = mapped_column(SmallInteger)
    posted_as: Mapped[str] = mapped_column(String(10), server_default=lit("personal"))
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer, server_default=ONE)
    content_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()

    board: Mapped[Board] = relationship(lazy="raise")
    stats: Mapped["PostStat"] = relationship(back_populates="post", lazy="raise")


# §4.7 — 고정 조건은 SQL 리터럴(부분 인덱스가 범용 계획에서도 쓰이게, §2.2 P4)
Index(
    "ix_posts_board_list",
    Post.board_id,
    Post.published_at.desc(),
    Post.id.desc(),
    # expires_at 을 함께 담아 목록 쪽 넘김·개수가 인덱스만 읽게 한다(1단계 측정: 개수 14ms → 5ms)
    postgresql_include=["expires_at"],
    postgresql_where=text("status = 'published' AND is_pinned = false"),
)
Index(
    "ix_posts_board_pinned",
    Post.board_id,
    Post.pin_order,
    postgresql_where=text("status = 'published' AND is_pinned"),
)
Index(
    "ix_posts_board_expires",
    Post.board_id,
    Post.expires_at,
    postgresql_where=text("expires_at IS NOT NULL"),
)
Index(
    "ix_posts_board_pending",
    Post.board_id,
    Post.created_at,
    postgresql_where=text("status = 'pending'"),
)
Index("ix_posts_trashed", Post.trashed_at, postgresql_where=text("status = 'trashed'"))
Index(
    "ix_posts_board_restricted",
    Post.board_id,
    postgresql_where=text(
        "status = 'published' AND (is_secret OR is_blinded OR min_view_level > 0)"
    ),
)
Index("ix_posts_member", Post.member_id, Post.created_at.desc())
Index("ix_posts_status_updated", Post.status, Post.updated_at.desc())
Index("ix_posts_sitemap", Post.published_at, postgresql_where=text("status = 'published'"))


class PostStat(Base):
    """카운터 분리 — 글 행의 잠금·갱신과 떼어 놓는다."""

    __tablename__ = "post_stats"

    post_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True
    )
    view_count: Mapped[int] = mapped_column(Integer, server_default=ZERO)
    like_count: Mapped[int] = mapped_column(Integer, server_default=ZERO)
    comment_count: Mapped[int] = mapped_column(Integer, server_default=ZERO)
    scrap_count: Mapped[int] = mapped_column(Integer, server_default=ZERO)
    share_count: Mapped[int] = mapped_column(Integer, server_default=ZERO)
    updated_at: Mapped[datetime] = updated_at()

    post: Mapped[Post] = relationship(back_populates="stats", lazy="raise")


class PostCategory(Base):
    __tablename__ = "post_categories"

    post_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True
    )
    category_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("board_categories.id", ondelete="RESTRICT"), primary_key=True
    )


Index("ix_post_categories_category", PostCategory.category_id, PostCategory.post_id)


class PostSearch(Base):
    """검색 색인 + 비정규화(§9). post_open 은 글 단위 조건만, 게시판 조건은 검색 때 조인한다."""

    __tablename__ = "post_search"

    post_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True
    )
    board_id: Mapped[int] = mapped_column(BigInteger)  # 비정규화 — FK 없음
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    post_open: Mapped[bool] = mapped_column(Boolean)
    grams: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    title_grams: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    content_compact: Mapped[str] = mapped_column(Text, server_default=text("''"))
    title_compact: Mapped[str] = mapped_column(Text, server_default=text("''"))
    updated_at: Mapped[datetime] = updated_at()


Index("ix_post_search_grams", PostSearch.grams, postgresql_using="gin")
Index("ix_post_search_title_grams", PostSearch.title_grams, postgresql_using="gin")
Index(
    "ix_post_search_open_published",
    PostSearch.published_at.desc(),
    postgresql_where=text("post_open"),
)


class PostRelation(Base):
    __tablename__ = "post_relations"
    __table_args__ = (
        CheckConstraint("source_post_id <> target_post_id", name="not_self"),
    )

    source_post_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True
    )
    target_post_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True
    )
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("members.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = created_at()


class PostTombstone(Base):
    """영구 삭제된 글 → 410."""

    __tablename__ = "post_tombstones"

    # 지워진 글의 id 를 그대로 담는다 — 자동 증가 아님
    post_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    board_slug: Mapped[str] = mapped_column(String(100))
    purged_at: Mapped[datetime] = created_at()


class PostReaction(Base):
    __tablename__ = "post_reactions"
    __table_args__ = (enum_check("kind", REACTION_KINDS),)

    post_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True
    )
    member_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("members.id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(String(10), primary_key=True, server_default=lit("like"))
    created_at: Mapped[datetime] = created_at()


class PostScrap(Base):
    __tablename__ = "post_scraps"

    post_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True
    )
    member_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("members.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = created_at()


Index("ix_post_scraps_member", PostScrap.member_id, PostScrap.created_at.desc())


class PostViewOnce(Base):
    __tablename__ = "post_view_once"

    post_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True
    )
    viewer_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = created_at()


class PostViewDaily(Base):
    __tablename__ = "post_view_daily"

    post_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True
    )
    viewer_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    view_date: Mapped[date] = mapped_column(Date, primary_key=True)
