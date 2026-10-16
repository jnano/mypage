"""보는 사람(Viewer) — 설계도 §5.1, 인증 설계도 §4.4.

요청당 한 번, 별도의 짧은 세션에서 만들고 연결을 바로 돌려준다(§3.1-4).
- 세션: Next 가 쿠키를 `X-Session` 으로 싣는다. **내부 비밀이 맞는 요청에서만** 받는다(rewrites 로 들어온
  브라우저 요청은 비회원). 쿼리 한 번(sessions ⋈ members), 읽기에는 쓰기가 없다.
- 개발용 헤더 `X-Dev-Member: {id}; key={공유 비밀}` 는 ENV=dev 전용(§11). 둘 다 오면 개발 헤더가 먼저다.
"""

import hmac
import logging
from dataclasses import dataclass, field
from typing import Literal

from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy import and_, func, literal_column, or_, select, update

from app.auth.sessions import hash_token
from app.core.config import settings
from app.core.csrf import SAFE_METHODS, is_internal
from app.core.problems import Problem
from app.db.session import SessionLocal
from app.models import LoginSession, Member, MemberGroupMember, MemberSanction

logger = logging.getLogger(__name__)

DEV_HEADER = "X-Dev-Member"
SESSION_HEADER = "X-Session"
TOUCH_EVERY = timedelta(minutes=10)  # 쓰기 요청의 last_write_at 갱신 간격(§3.2)


@dataclass(frozen=True)
class Viewer:
    member_id: int | None
    level: int  # 0 = 비회원
    is_admin: bool = False
    group_ids: frozenset[int] = field(default_factory=frozenset)
    # 지금 걸린 **사이트 전체** 정지('write','comment','upload'). 게시판 단위 정지는 BoardRole.sanctions
    sanctions: frozenset[str] = field(default_factory=frozenset)
    # 세션으로 들어온 요청이면 그 세션 id(로그아웃·'이 세션을 뺀 나머지 폐기'), 개발 헤더면 None
    session_id: int | None = None

    @property
    def is_member(self) -> bool:
        return self.member_id is not None


GUEST = Viewer(member_id=None, level=0)


@dataclass(frozen=True)
class GuestToken:
    """검증을 마친 비회원 토큰의 내용(서명 확인은 토큰 모듈이 한다). edit 토큰은 read 도 허용한다."""

    post_id: int
    purpose: Literal["read", "edit"]

    def allows(self, post_id: int, purpose: Literal["read", "edit"]) -> bool:
        return self.post_id == post_id and (self.purpose == purpose or self.purpose == "edit")


def active_sanction_clause():
    """지금 유효한 제재 — 부분 인덱스 ix_member_sanctions_active 의 조건(revoked_at IS NULL)을 포함한다."""
    return and_(
        MemberSanction.revoked_at.is_(None),
        MemberSanction.starts_at <= func.now(),
        or_(MemberSanction.ends_at.is_(None), MemberSanction.ends_at > func.now()),
    )


def _parse_dev_header(value: str) -> tuple[int, str]:
    try:
        id_part, key_part = (p.strip() for p in value.split(";", 1))
        if not key_part.startswith("key="):
            raise ValueError
        return int(id_part), key_part.removeprefix("key=")
    except ValueError:
        raise Problem(401, "dev_viewer_invalid", "개발용 Viewer 헤더 형식이 올바르지 않습니다") from None


def _viewer_select():
    """회원 + 그룹 id 배열 + 사이트 전체 정지 배열 — 회원 하나를 쿼리 한 번에"""
    groups = select(MemberGroupMember.group_id).where(MemberGroupMember.member_id == Member.id)
    sanctions = select(func.unnest(MemberSanction.actions)).where(
        MemberSanction.member_id == Member.id,
        MemberSanction.scope_board_id.is_(None),
        active_sanction_clause(),
    )
    return select(
        Member.id,
        Member.level,
        Member.is_admin,
        func.array(groups.scalar_subquery()).label("group_ids"),
        func.array(sanctions.scalar_subquery()).label("sanctions"),
    )


def _viewer(row, session_id: int | None = None) -> Viewer:
    return Viewer(
        member_id=row.id,
        level=row.level,
        is_admin=row.is_admin,
        group_ids=frozenset(row.group_ids),
        sanctions=frozenset(row.sanctions),
        session_id=session_id,
    )


async def load_viewer(member_id: int) -> Viewer:
    """회원 하나의 Viewer. 탈퇴했거나 없는 회원은 비회원으로 본다."""
    stmt = _viewer_select().where(Member.id == member_id, Member.status == literal_column("'active'"))
    async with SessionLocal() as db:
        row = (await db.execute(stmt)).one_or_none()
    return GUEST if row is None else _viewer(row)


async def load_session_viewer(token: str, touch: bool) -> Viewer:
    """세션 토큰의 Viewer — 해시 일치 ∧ 폐기 안 됨 ∧ 만료 전 ∧ 활동 회원. 아니면 비회원(401 을 내지 않는다).
    touch 면(쓰기 요청) last_write_at 이 10분 넘게 지났을 때만 짧은 autocommit 으로 갱신한다."""
    stmt = (
        _viewer_select()
        .add_columns(LoginSession.id.label("session_id"), LoginSession.last_write_at)
        .join(LoginSession, LoginSession.member_id == Member.id)
        .where(
            LoginSession.token_hash == hash_token(token),
            LoginSession.revoked_at.is_(None),
            LoginSession.expires_at > func.now(),
            Member.status == literal_column("'active'"),
        )
    )
    async with SessionLocal() as db:
        row = (await db.execute(stmt)).one_or_none()
        if row is None:
            return GUEST
        if touch and row.last_write_at < datetime.now(UTC) - TOUCH_EVERY:
            await db.execute(
                update(LoginSession).where(LoginSession.id == row.session_id).values(last_write_at=func.now())
            )
            await db.commit()
    return _viewer(row, session_id=row.session_id)


async def get_viewer(request: Request) -> Viewer:
    """FastAPI 의존성. 개발용 헤더(켜져 있을 때만) → 세션(내부 비밀이 맞을 때만) → 비회원."""
    raw = request.headers.get(DEV_HEADER)
    if not settings.dev_viewer_header or raw is None:
        token = request.headers.get(SESSION_HEADER)
        if not token or len(token) > 200 or not is_internal(request):
            return GUEST
        return await load_session_viewer(token, touch=request.method not in SAFE_METHODS)
    member_id, key = _parse_dev_header(raw)
    if not hmac.compare_digest(key.encode(), settings.dev_viewer_secret.encode()):
        raise Problem(401, "dev_viewer_invalid", "개발용 Viewer 헤더의 비밀 값이 맞지 않습니다")
    return await load_viewer(member_id)
