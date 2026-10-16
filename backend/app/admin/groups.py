"""회원 그룹(명부) 관리 — 인증 설계도 §5 '그룹 관리'. 그룹은 게시판 명부(board_access)의 주체다."""

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import delete, func, literal_column, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.logs import LogEntry, record
from app.auth.viewer import Viewer
from app.core.problems import Problem
from app.models import BoardAccess, Member, MemberGroup, MemberGroupMember

MAX_MEMBERS = 5000


class GroupBody(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    description: str | None = Field(default=None, max_length=1000)


class GroupPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=50)
    description: str | None = Field(default=None, max_length=1000)


class GroupMembers(BaseModel):
    member_ids: list[int] = Field(max_length=MAX_MEMBERS)


def _conflict() -> Problem:
    return Problem(409, "group_exists", "같은 이름의 그룹이 있습니다")


async def list_groups(db: AsyncSession) -> list[dict[str, Any]]:
    counts = (
        select(MemberGroupMember.group_id, func.count().label("n")).group_by(MemberGroupMember.group_id).subquery()
    )
    rows = (
        await db.execute(
            select(MemberGroup.id, MemberGroup.name, MemberGroup.description, func.coalesce(counts.c.n, 0).label("members"))
            .outerjoin(counts, counts.c.group_id == MemberGroup.id)
            .order_by(MemberGroup.name)
        )
    ).all()
    return [{"id": r.id, "name": r.name, "description": r.description, "members": r.members} for r in rows]


async def group_detail(db: AsyncSession, group_id: int) -> dict[str, Any]:
    group = await db.get(MemberGroup, group_id)
    if group is None:
        raise Problem(404, "group_not_found", "그룹을 찾을 수 없습니다")
    members = (
        await db.execute(
            select(Member.id, Member.display_name, Member.email)
            .join(MemberGroupMember, MemberGroupMember.member_id == Member.id)
            .where(MemberGroupMember.group_id == group_id)
            .order_by(Member.display_name)
        )
    ).all()
    return {
        "id": group.id,
        "name": group.name,
        "description": group.description,
        "members": [{"id": m.id, "display_name": m.display_name, "email": m.email} for m in members],
    }


async def create_group(db: AsyncSession, viewer: Viewer, body: GroupBody) -> dict[str, Any]:
    group = MemberGroup(name=body.name.strip(), description=body.description)
    db.add(group)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise _conflict() from None
    await record(db, viewer, [LogEntry("group.create", "group", group.id, after={"name": group.name})])
    return await group_detail(db, group.id)


async def update_group(db: AsyncSession, viewer: Viewer, group_id: int, patch: GroupPatch) -> dict[str, Any]:
    group = await db.get(MemberGroup, group_id, with_for_update=True)
    if group is None:
        raise Problem(404, "group_not_found", "그룹을 찾을 수 없습니다")
    before = {"name": group.name}
    if patch.name is not None:
        group.name = patch.name.strip()
    if patch.description is not None:
        group.description = patch.description or None
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise _conflict() from None
    await record(db, viewer, [LogEntry("group.update", "group", group.id, before=before, after={"name": group.name})])
    return await group_detail(db, group.id)


async def delete_group(db: AsyncSession, viewer: Viewer, group_id: int) -> None:
    """그룹 삭제 — 게시판 명부의 그 그룹 행도 함께(다형 참조라 FK 가 없다, 본 설계서 §4.2)"""
    group = await db.get(MemberGroup, group_id, with_for_update=True)
    if group is None:
        raise Problem(404, "group_not_found", "그룹을 찾을 수 없습니다")
    await db.execute(delete(BoardAccess).where(BoardAccess.subject_type == "group", BoardAccess.subject_id == group_id))
    await db.delete(group)  # 소속 행은 FK CASCADE
    await record(db, viewer, [LogEntry("group.delete", "group", group_id, before={"name": group.name})])


async def set_members(db: AsyncSession, viewer: Viewer, group_id: int, member_ids: list[int]) -> dict[str, Any]:
    """소속 회원을 통째로 바꾼다 — 활동 회원만 받는다(없는·탈퇴 회원 id 는 422)"""
    group = await db.get(MemberGroup, group_id, with_for_update=True)
    if group is None:
        raise Problem(404, "group_not_found", "그룹을 찾을 수 없습니다")
    wanted = set(member_ids)
    found = set(
        (await db.execute(select(Member.id).where(Member.id.in_(wanted), Member.status == literal_column("'active'")))).scalars()
    ) if wanted else set()  # fmt: skip
    if missing := sorted(wanted - found):
        raise Problem(422, "validation_error", "활동 회원이 아닌 번호가 있습니다", errors=[{"field": "member_ids", "message": ", ".join(map(str, missing[:20]))}])
    current = set((await db.execute(select(MemberGroupMember.member_id).where(MemberGroupMember.group_id == group_id))).scalars())
    if removed := current - wanted:
        await db.execute(delete(MemberGroupMember).where(MemberGroupMember.group_id == group_id, MemberGroupMember.member_id.in_(removed)))
    if added := wanted - current:
        await db.execute(insert(MemberGroupMember).values([{"group_id": group_id, "member_id": m} for m in sorted(added)]).on_conflict_do_nothing())
    if added or removed:
        await record(db, viewer, [LogEntry("group.members", "group", group_id, after={"added": sorted(added), "removed": sorted(removed)})])
    return await group_detail(db, group_id)
