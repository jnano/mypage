"""보는 사람(Viewer) — 설계도 §5.1.

요청당 한 번, 별도의 짧은 세션에서 만들고 연결을 바로 돌려준다(§3.1-4).
골격은 개발용 헤더 `X-Dev-Member: {id}; key={공유 비밀}` 로 만든다(ENV=dev 전용, §11).
인증을 붙일 때는 get_viewer 만 바꾼다 — Viewer 인터페이스는 그대로다.
"""

import hmac
import logging
from dataclasses import dataclass, field
from typing import Literal

from fastapi import Request
from sqlalchemy import and_, func, literal_column, or_, select

from app.core.config import settings
from app.core.problems import Problem
from app.db.session import SessionLocal
from app.models import Member, MemberGroupMember, MemberSanction

logger = logging.getLogger(__name__)

DEV_HEADER = "X-Dev-Member"


@dataclass(frozen=True)
class Viewer:
    member_id: int | None
    level: int  # 0 = 비회원
    is_admin: bool = False
    group_ids: frozenset[int] = field(default_factory=frozenset)
    # 지금 걸린 **사이트 전체** 정지('write','comment','upload'). 게시판 단위 정지는 BoardRole.sanctions
    sanctions: frozenset[str] = field(default_factory=frozenset)

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


async def load_viewer(member_id: int) -> Viewer:
    """회원 하나의 Viewer. 탈퇴했거나 없는 회원은 비회원으로 본다."""
    # 쿼리 한 번: 회원 + 그룹 id 배열 + 사이트 전체 정지 배열
    groups = select(MemberGroupMember.group_id).where(MemberGroupMember.member_id == Member.id)
    sanctions = select(func.unnest(MemberSanction.actions)).where(
        MemberSanction.member_id == Member.id,
        MemberSanction.scope_board_id.is_(None),
        active_sanction_clause(),
    )
    stmt = select(
        Member.id,
        Member.level,
        Member.is_admin,
        func.array(groups.scalar_subquery()).label("group_ids"),
        func.array(sanctions.scalar_subquery()).label("sanctions"),
    ).where(Member.id == member_id, Member.status == literal_column("'active'"))
    async with SessionLocal() as db:
        row = (await db.execute(stmt)).one_or_none()
    if row is None:
        return GUEST
    return Viewer(
        member_id=row.id,
        level=row.level,
        is_admin=row.is_admin,
        group_ids=frozenset(row.group_ids),
        sanctions=frozenset(row.sanctions),
    )


async def get_viewer(request: Request) -> Viewer:
    """FastAPI 의존성. 개발용 헤더가 꺼져 있으면 헤더를 무시하고 비회원으로 본다."""
    raw = request.headers.get(DEV_HEADER)
    if not settings.dev_viewer_header or raw is None:
        return GUEST
    member_id, key = _parse_dev_header(raw)
    if not hmac.compare_digest(key.encode(), settings.dev_viewer_secret.encode()):
        raise Problem(401, "dev_viewer_invalid", "개발용 Viewer 헤더의 비밀 값이 맞지 않습니다")
    return await load_viewer(member_id)
