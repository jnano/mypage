"""회원·설정 — 설계도 §4.1"""

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
    )

    id: Mapped[int] = pk_id()
    display_name: Mapped[str] = mapped_column(String(50))
    level: Mapped[int] = mapped_column(SmallInteger, server_default=ONE)
    is_admin: Mapped[bool] = mapped_column(Boolean, server_default=FALSE)
    status: Mapped[str] = mapped_column(String(10), server_default=lit("active"))
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


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
