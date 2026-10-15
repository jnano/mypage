"""제재(작성 정지) — 설계도 §5.3·§14.2 '제재'. 판정은 이미 Viewer.sanctions(사이트)·BoardRole.sanctions(게시판)가 본다.

담당자는 자기 게시판 범위로만 걸고 풀 수 있다. 사이트 전체 정지는 운영자만. 해제는 revoked_at(행은 남긴다).
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, insert, literal_column, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.logs import LogEntry, record
from app.admin.scope import StaffScope
from app.auth.viewer import active_sanction_clause
from app.core.problems import Problem
from app.models import Board, Member, MemberSanction


async def create(
    db: AsyncSession, scope: StaffScope, *, member_id: int, board_id: int | None, actions: list[str], days: int | None, reason: str
) -> int:
    if board_id is None:
        scope.require_admin()
    else:
        scope.require_board(board_id)
    member = (await db.execute(select(Member.id, Member.is_admin).where(Member.id == member_id, Member.status == literal_column("'active'")))).one_or_none()
    if member is None:
        raise Problem(404, "member_not_found", "회원을 찾을 수 없습니다")
    if member.is_admin:
        raise Problem(409, "admin_not_sanctionable", "사이트 운영자는 정지할 수 없습니다")  # 운영자는 판정에서 정지를 우회한다(§5.3)
    ends_at = datetime.now(UTC) + timedelta(days=days) if days else None
    sanction_id = (
        await db.execute(
            insert(MemberSanction)
            .values(member_id=member_id, scope_board_id=board_id, actions=actions, ends_at=ends_at, reason=reason, created_by=scope.viewer.member_id)
            .returning(MemberSanction.id)
        )
    ).scalar_one()
    await record(
        db,
        scope.viewer,
        [LogEntry("sanction.create", "sanction", sanction_id, board_id=board_id, after={"author_id": member_id, "actions": actions, "ends_at": ends_at.isoformat() if ends_at else None}, reason=reason)],
    )
    return sanction_id


async def revoke(db: AsyncSession, scope: StaffScope, sanction_id: int, reason: str | None) -> None:
    row = (await db.execute(select(MemberSanction).where(MemberSanction.id == sanction_id).with_for_update())).scalar_one_or_none()
    if row is None:
        raise Problem(404, "sanction_not_found", "제재를 찾을 수 없습니다")
    if row.scope_board_id is None:
        scope.require_admin()
    else:
        scope.require_board(row.scope_board_id)
    if row.revoked_at is not None:
        return
    await db.execute(update(MemberSanction).where(MemberSanction.id == sanction_id).values(revoked_at=func.now()))
    await record(db, scope.viewer, [LogEntry("sanction.revoke", "sanction", sanction_id, board_id=row.scope_board_id, before={"author_id": row.member_id}, reason=reason)])


async def list_sanctions(db: AsyncSession, scope: StaffScope, *, member_id: int | None, active_only: bool) -> list[dict[str, Any]]:
    stmt = (
        select(MemberSanction, Member.display_name, Board.slug)
        .join(Member, Member.id == MemberSanction.member_id)
        .outerjoin(Board, Board.id == MemberSanction.scope_board_id)
        .order_by(MemberSanction.id.desc())
        .limit(200)
    )
    if not scope.is_admin:
        stmt = stmt.where(scope.board_clause(MemberSanction.scope_board_id))  # 담당자는 자기 게시판 범위만(사이트 전체 정지는 안 보임)
    if member_id is not None:
        stmt = stmt.where(MemberSanction.member_id == member_id)
    if active_only:
        stmt = stmt.where(active_sanction_clause())
    rows = (await db.execute(stmt)).all()
    now = datetime.now(UTC)
    return [
        {
            "id": s.id,
            "member": {"id": s.member_id, "name": name},
            "board": {"id": s.scope_board_id, "slug": slug} if s.scope_board_id else None,
            "actions": s.actions,
            "starts_at": s.starts_at.isoformat(),
            "ends_at": s.ends_at.isoformat() if s.ends_at else None,
            "reason": s.reason,
            "revoked_at": s.revoked_at.isoformat() if s.revoked_at else None,
            "active": s.revoked_at is None and s.starts_at <= now and (s.ends_at is None or s.ends_at > now),
        }
        for s, name, slug in rows
    ]
