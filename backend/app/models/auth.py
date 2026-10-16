"""인증 — 인증 설계도 §3.2~§3.6(세션·재설정 토큰·승급 신청·탈퇴 표시·개인정보 고지 판)"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    SmallInteger,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models._columns import created_at, enum_check, lit, pk_id
from app.models.enums import LEVEL_REQUEST_STATUSES


class LoginSession(Base):
    """로그인 세션 — 토큰 원문은 저장하지 않는다(SHA-256 만). 읽기 요청은 이 행을 쓰지 않는다(§4.4)"""

    __tablename__ = "sessions"

    id: Mapped[int] = pk_id()
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    member_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("members.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = created_at()
    # 쓰기 경로와 로그인에서만 갱신(10분 간격) — 화면의 '마지막 활동(글쓰기 등)'
    last_write_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    persistent: Mapped[bool] = mapped_column(Boolean)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(200))


Index("ix_sessions_member", LoginSession.member_id, postgresql_where=text("revoked_at IS NULL"))


class PasswordResetToken(Base):
    """운영자가 발급하는 재설정 링크(메일 없는 동안, §4.8) — 24시간·1회"""

    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = pk_id()
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    member_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("members.id", ondelete="CASCADE"))
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("members.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LevelRequest(Base):
    """레벨 승급 신청(§4.10) — 한 사람은 한 번에 하나만"""

    __tablename__ = "level_requests"
    __table_args__ = (
        CheckConstraint("to_level > from_level", name="levels"),
        enum_check("status", LEVEL_REQUEST_STATUSES),
        CheckConstraint("status <> 'rejected' OR decision_note IS NOT NULL", name="decision_note"),
    )

    id: Mapped[int] = pk_id()
    member_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("members.id", ondelete="CASCADE"))
    from_level: Mapped[int] = mapped_column(SmallInteger)
    to_level: Mapped[int] = mapped_column(SmallInteger)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), server_default=lit("pending"))
    decided_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("members.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = created_at()


Index(
    "uq_level_requests_pending",
    LevelRequest.member_id,
    unique=True,
    postgresql_where=text("status = 'pending'"),
)
Index("ix_level_requests_queue", LevelRequest.created_at, postgresql_where=text("status = 'pending'"))


class WithdrawnEmailMark(Base):
    """제재 중에 탈퇴한 주소의 HMAC(§3.5) — 가입 대기열에 표시만 한다. 원문 없음"""

    __tablename__ = "withdrawn_email_marks"

    email_hmac: Mapped[bytes] = mapped_column(LargeBinary, primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PrivacyNotice(Base):
    """개인정보 고지 판(§3.6) — 게시한 판은 고치지 않는다(새 판을 만든다)"""

    __tablename__ = "privacy_notices"

    version: Mapped[str] = mapped_column(String(20), primary_key=True)
    body: Mapped[str] = mapped_column(Text)
    requires_reconsent: Mapped[bool] = mapped_column(Boolean)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # NULL = 초안
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("members.id", ondelete="SET NULL"))
