"""회원·설정 — 설계도 §4.1, 인증 칸은 인증 설계도 §3.1"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import Index, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models._columns import FALSE, ONE, created_at, enum_check, lit, pk_id, range_check, updated_at
from app.models.enums import MEMBER_STATUSES


class Member(Base):
    __tablename__ = "members"
    __table_args__ = (
        range_check("level", 1, 99),
        enum_check("status", MEMBER_STATUSES),
        CheckConstraint("(status = 'withdrawn') = (withdrawn_at IS NOT NULL)", name="withdrawn"),
        # 인증 설계도 §3.1 — 가입 대기·활동 회원은 로그인·동의 칸이 모두 있고, 탈퇴 회원은 개인 칸이 비어 있다.
        # 마이그레이션은 이 둘을 칸 추가와 나눠 건다(채우지 않은 기존 행이 있으면 안내와 함께 실패)
        CheckConstraint(
            "status = 'withdrawn' OR (email IS NOT NULL AND password_hash IS NOT NULL"
            " AND display_name_key IS NOT NULL AND privacy_version IS NOT NULL"
            " AND privacy_agreed_at IS NOT NULL AND age14_confirmed_at IS NOT NULL)",
            name="live_fields",
        ),
        CheckConstraint(
            "status <> 'withdrawn' OR (email IS NULL AND password_hash IS NULL"
            " AND display_name_key IS NULL AND signup_note IS NULL)",
            name="withdrawn_cleared",
        ),
    )

    id: Mapped[int] = pk_id()
    display_name: Mapped[str] = mapped_column(String(50))
    level: Mapped[int] = mapped_column(SmallInteger, server_default=ONE)
    is_admin: Mapped[bool] = mapped_column(Boolean, server_default=FALSE)
    status: Mapped[str] = mapped_column(String(10), server_default=lit("active"))
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()
    # 인증(인증 설계도 §3.1) — 이메일은 정규화(공백 제거 + 소문자)해 저장한다
    email: Mapped[str | None] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))  # argon2id
    # 표시 이름 정규화 키(§7.6) — 활동 회원끼리만 고유. NFKC 가 글자 수를 늘릴 수 있어 이름 칸보다 넉넉히
    display_name_key: Mapped[str | None] = mapped_column(String(200))
    signup_note: Mapped[str | None] = mapped_column(String(500))
    age14_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("members.id", ondelete="SET NULL"))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_reset_by_admin_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 마지막으로 동의한 고지 판. privacy_notices.created_by 와 서로 참조하므로 FK 는 표를 만든 뒤 건다(use_alter)
    privacy_version: Mapped[str | None] = mapped_column(
        String(20), ForeignKey("privacy_notices.version", ondelete="RESTRICT", use_alter=True)
    )
    privacy_agreed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


Index(
    "uq_members_display_name_key",
    Member.display_name_key,
    unique=True,
    postgresql_where=text("status = 'active'"),
)


class MemberGroup(Base):
    __tablename__ = "member_groups"

    id: Mapped[int] = pk_id()
    name: Mapped[str] = mapped_column(String(50), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()


class MemberGroupMember(Base):
    __tablename__ = "member_group_members"

    group_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("member_groups.id", ondelete="CASCADE"), primary_key=True
    )
    member_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("members.id", ondelete="CASCADE"), primary_key=True
    )


class SiteSetting(Base):
    __tablename__ = "site_settings"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = updated_at()
    updated_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("members.id", ondelete="SET NULL")
    )
