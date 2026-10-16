"""댓글·첨부 — 설계도 §4.4"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    CHAR,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    and_,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models._columns import FALSE, ZERO, created_at, enum_check, lit, pk_id, updated_at
from app.models.enums import (
    ATTACHMENT_ROLES,
    ATTACHMENT_VISIBILITIES,
    BLIND_SOURCES,
    COMMENT_STATUSES,
)
from app.models.posts import Post


class Comment(Base):
    """평문 댓글. 답글은 1단까지 — 부모의 parent_id 가 NULL 인지는 API 가 검증한다."""

    __tablename__ = "comments"
    __table_args__ = (
        enum_check("status", COMMENT_STATUSES),
        enum_check("blind_source", BLIND_SOURCES),
        CheckConstraint("blind_source IS NULL OR is_blinded", name="blind_source"),
    )

    id: Mapped[int] = pk_id()
    post_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("posts.id", ondelete="CASCADE"))
    member_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("members.id", ondelete="SET NULL")
    )
    author_name_snapshot: Mapped[str] = mapped_column(String(50))
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("comments.id", ondelete="CASCADE")
    )
    reply_to_comment_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("comments.id", ondelete="SET NULL")
    )
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), server_default=lit("published"))
    is_blinded: Mapped[bool] = mapped_column(Boolean, server_default=FALSE)
    blind_source: Mapped[str | None] = mapped_column(String(12))
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()

    post: Mapped[Post] = relationship(lazy="raise")


Index("ix_comments_post", Comment.post_id, Comment.created_at)
Index("ix_comments_member", Comment.member_id, Comment.created_at.desc())
# 글 영구 삭제의 연쇄(CASCADE·SET NULL)가 지워지는 댓글마다 찾는 칸 — 없으면 댓글마다 표 전체를 훑는다(3단계 측정 §4.7)
Index("ix_comments_parent", Comment.parent_id, postgresql_where=text("parent_id IS NOT NULL"))
Index("ix_comments_reply_to", Comment.reply_to_comment_id, postgresql_where=text("reply_to_comment_id IS NOT NULL"))


# 임시 업로드의 정의(홈블록 §4.7) — 정리 작업·인덱스 부분 조건·붙이기·임시 삭제가 모두 이것을 쓴다
TEMP_UPLOAD_SQL = "post_id IS NULL AND block_id IS NULL"


class Attachment(Base):
    __tablename__ = "attachments"
    __table_args__ = (
        enum_check("role", ATTACHMENT_ROLES),
        enum_check("visibility", ATTACHMENT_VISIBILITIES),
        CheckConstraint("(width IS NULL) = (height IS NULL)", name="dimensions"),
        CheckConstraint("post_id IS NULL OR block_id IS NULL", name="one_owner"),
    )

    id: Mapped[int] = pk_id()
    # post_id·block_id 둘 다 NULL = 어디에도 붙기 전 임시 업로드(24시간 뒤 정리, TEMP_UPLOAD)
    post_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("posts.id", ondelete="CASCADE")
    )
    uploader_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("members.id", ondelete="SET NULL")
    )
    role: Mapped[str] = mapped_column(String(10), server_default=lit("attachment"))
    original_name: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(80), unique=True)
    visibility: Mapped[str] = mapped_column(String(8), server_default=lit("private"))
    sha256: Mapped[str] = mapped_column(CHAR(64))
    detected_mime: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    is_image: Mapped[bool] = mapped_column(Boolean, server_default=FALSE)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    exif_stripped: Mapped[bool] = mapped_column(Boolean, server_default=FALSE)
    thumbs_ready: Mapped[bool] = mapped_column(Boolean, server_default=FALSE)
    sort_order: Mapped[int] = mapped_column(SmallInteger, server_default=ZERO)
    is_cover: Mapped[bool] = mapped_column(Boolean, server_default=FALSE)
    alt_text: Mapped[str | None] = mapped_column(String(300))
    download_count: Mapped[int] = mapped_column(Integer, server_default=ZERO)
    created_at: Mapped[datetime] = created_at()
    # 블록 그림(홈블록 §4.7). 블록이 지워지면 NULL → 임시가 되어 정리된다
    block_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("blocks.id", ondelete="SET NULL"))

    post: Mapped[Post | None] = relationship(lazy="raise")


Index("ix_attachments_post", Attachment.post_id, Attachment.sort_order)
# ORM 쪽 같은 조건
TEMP_UPLOAD = and_(Attachment.post_id.is_(None), Attachment.block_id.is_(None))

Index("ix_attachments_block", Attachment.block_id, postgresql_where=text("block_id IS NOT NULL"))
Index("ix_attachments_temp", Attachment.created_at, postgresql_where=text(TEMP_UPLOAD_SQL))
