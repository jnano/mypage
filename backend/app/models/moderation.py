"""신고·운영 기록·제재 — 설계도 §4.5"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models._columns import created_at, enum_check, lit, pk_id
from app.models.enums import (
    MODERATION_TARGET_TYPES,
    REPORT_STATUSES,
    REPORT_TARGET_TYPES,
    SANCTION_ACTIONS,
)


class Report(Base):
    """target_id 는 다형 참조라 FK 가 없다."""

    __tablename__ = "reports"
    __table_args__ = (
        enum_check("target_type", REPORT_TARGET_TYPES),
        enum_check("status", REPORT_STATUSES),
        UniqueConstraint("target_type", "target_id", "reporter_id"),
    )

    id: Mapped[int] = pk_id()
    target_type: Mapped[str] = mapped_column(String(8))
    target_id: Mapped[int] = mapped_column(BigInteger)
    board_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("boards.id", ondelete="SET NULL")
    )
    reporter_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("members.id", ondelete="SET NULL")
    )
    reason_code: Mapped[str] = mapped_column(String(20))
    reason_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), server_default=lit("open"))
    handled_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("members.id", ondelete="SET NULL")
    )
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()


Index(
    "ix_reports_open",
    Report.status,
    Report.created_at,
    postgresql_where=text("status = 'open'"),
)


class ModerationLog(Base):
    """행은 지우지 않는다. before/after 는 바뀐 칸만(§4.5), 개인 값 가림은 §14.4."""

    __tablename__ = "moderation_logs"
    __table_args__ = (enum_check("target_type", MODERATION_TARGET_TYPES),)

    id: Mapped[int] = pk_id()
    actor_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("members.id", ondelete="SET NULL")
    )
    board_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("boards.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(40))
    target_type: Mapped[str] = mapped_column(String(10))
    target_id: Mapped[int] = mapped_column(BigInteger)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()
    redacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MemberSanction(Base):
    __tablename__ = "member_sanctions"
    __table_args__ = (
        CheckConstraint(
            "actions <@ ARRAY["
            + ", ".join(f"'{a}'" for a in SANCTION_ACTIONS)
            + "]::text[] AND cardinality(actions) > 0",
            name="actions",
        ),
    )

    id: Mapped[int] = pk_id()
    member_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("members.id", ondelete="CASCADE")
    )
    # NULL = 사이트 전체
    scope_board_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("boards.id", ondelete="CASCADE")
    )
    actions: Mapped[list[str]] = mapped_column(ARRAY(Text))
    starts_at: Mapped[datetime] = created_at()
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("members.id", ondelete="SET NULL")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()


Index(
    "ix_member_sanctions_active",
    MemberSanction.member_id,
    postgresql_where=text("revoked_at IS NULL"),
)
