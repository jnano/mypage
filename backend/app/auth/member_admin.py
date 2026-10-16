"""회원 관리(운영자) — 인증 설계도 §4.7·§4.10-5·§4.11·§4.13·§5 '회원 관리'.

목록·상세·고치기(레벨·표시 이름·이메일·운영자 지정)·강제 로그아웃. 이메일 변경·운영자 지정·해제·강제 로그아웃은
운영자 본인 비밀번호 재확인(§4.13). 운영 기록에는 이메일 원문을 넣지 않는다(§3.8).
탈퇴·재설정 링크는 app/auth/account.py.
"""

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, literal_column, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.logs import LogEntry, record
from app.auth import sessions
from app.auth.account import lock_admins, reauth
from app.auth.emails import checked_email, mask_email
from app.auth.names import clean_display_name, display_name_key
from app.auth.viewer import Viewer
from app.core.config import settings
from app.core.problems import Problem
from app.models import LevelRequest, LoginSession, Member, MemberGroup, MemberGroupMember

PAGE = 50


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def list_members(
    db: AsyncSession, *, status: Literal["active", "withdrawn"], q: str | None, after_id: int | None
) -> dict[str, Any]:
    """회원 목록(운영자만 — 이메일 포함). 최근 가입 순, id 커서. q 는 이메일·표시 이름 부분 일치"""
    stmt = (
        select(
            Member.id, Member.email, Member.display_name, Member.level, Member.is_admin,
            Member.created_at, Member.last_login_at, Member.withdrawn_at,
        )  # fmt: skip
        .where(Member.status == status)
        .order_by(Member.id.desc())
        .limit(PAGE + 1)
    )
    if q and q.strip():
        pattern = f"%{_escape_like(q.strip().lower())}%"
        stmt = stmt.where(or_(Member.email.like(pattern, escape="\\"), func.lower(Member.display_name).like(pattern, escape="\\")))
    if after_id is not None:
        stmt = stmt.where(Member.id < after_id)
    rows = (await db.execute(stmt)).all()
    more = len(rows) > PAGE
    rows = rows[:PAGE]
    return {
        "items": [
            {
                "id": r.id,
                "email": r.email,
                "display_name": r.display_name,
                "level": r.level,
                "is_admin": r.is_admin,
                "created_at": r.created_at.isoformat(),
                "last_login_at": r.last_login_at.isoformat() if r.last_login_at else None,
                "withdrawn_at": r.withdrawn_at.isoformat() if r.withdrawn_at else None,
            }
            for r in rows
        ],
        "next_after": rows[-1].id if more else None,
    }


async def member_detail(db: AsyncSession, member_id: int) -> dict[str, Any]:
    member = await db.get(Member, member_id)
    if member is None or member.status == "pending":
        raise Problem(404, "member_not_found", "회원을 찾을 수 없습니다")
    groups = (
        await db.execute(
            select(MemberGroup.id, MemberGroup.name)
            .join(MemberGroupMember, MemberGroupMember.group_id == MemberGroup.id)
            .where(MemberGroupMember.member_id == member_id)
            .order_by(MemberGroup.name)
        )
    ).all()
    active_sessions = (
        await db.execute(
            select(func.count())
            .select_from(LoginSession)
            .where(LoginSession.member_id == member_id, LoginSession.revoked_at.is_(None), LoginSession.expires_at > func.now())
        )
    ).scalar_one()
    return {
        "id": member.id,
        "status": member.status,
        "email": member.email,
        "display_name": member.display_name,
        "level": member.level,
        "is_admin": member.is_admin,
        "created_at": member.created_at.isoformat(),
        "approved_at": member.approved_at.isoformat() if member.approved_at else None,
        "last_login_at": member.last_login_at.isoformat() if member.last_login_at else None,
        "password_changed_at": member.password_changed_at.isoformat() if member.password_changed_at else None,
        "groups": [{"id": g.id, "name": g.name} for g in groups],
        "active_sessions": active_sessions,
    }


class MemberPatch(BaseModel):
    level: int | None = Field(default=None, ge=1, le=99)
    display_name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    is_admin: bool | None = None
    password: str | None = Field(default=None, max_length=1024)  # 이메일·운영자 지정을 바꿀 때 운영자 본인 재확인
    reason: str | None = Field(default=None, max_length=500)


async def _active(db: AsyncSession, member_id: int) -> Member:
    member = (
        await db.execute(
            select(Member).where(Member.id == member_id, Member.status == literal_column("'active'")).with_for_update()
        )
    ).scalar_one_or_none()
    if member is None:
        raise Problem(404, "member_not_found", "활동 회원을 찾을 수 없습니다")
    return member


async def shrink_sessions(db: AsyncSession, member_id: int, is_admin: bool) -> None:
    """운영자 지정·해제 뒤 세션 만료를 새 기준으로 줄인다 — 늘리지는 않는다(§3.2.1)"""
    persistent_days = settings.session_admin_days if is_admin else settings.session_member_days
    limit = LoginSession.created_at + func.make_interval(0, 0, 0, persistent_days)
    await db.execute(
        update(LoginSession)
        .where(LoginSession.member_id == member_id, LoginSession.revoked_at.is_(None), LoginSession.persistent.is_(True))
        .values(expires_at=func.least(LoginSession.expires_at, limit))
    )


async def patch_member(db: AsyncSession, viewer: Viewer, member_id: int, patch: MemberPatch) -> dict[str, Any]:
    sensitive = patch.email is not None or patch.is_admin is not None
    if sensitive:
        if not patch.password:
            raise Problem(422, "validation_error", "비밀번호를 다시 입력해 주세요", errors=[{"field": "password", "message": "필수"}])
        await reauth(db, viewer, patch.password)
    # 운영자 지정이 바뀌면 운영자 행 전체를 id 순으로 **먼저** 잠근다 — 대상 행을 먼저 잠그면 두 운영자가 서로를
    # 해제할 때 잠금 순서가 엇갈려 교착된다(§4.11 '잠그는 순서 고정', 시험으로 찾음)
    admins = await lock_admins(db) if patch.is_admin is not None else []
    member = await _active(db, member_id)
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    if patch.level is not None and patch.level != member.level:
        before["level"], after["level"] = member.level, patch.level
        member.level = patch.level
        # 운영자가 레벨을 직접 바꾸면 대기 중인 승급 신청을 닫는다(§4.10-5)
        await db.execute(
            update(LevelRequest)
            .where(LevelRequest.member_id == member.id, LevelRequest.status == literal_column("'pending'"))
            .values(status="cancelled", decided_by=viewer.member_id, decided_at=datetime.now(UTC), decision_note="운영자가 레벨을 바꿈")
        )
    if patch.display_name is not None:
        try:
            name = clean_display_name(patch.display_name)
            key = display_name_key(name)
            if len(name) > 50:
                raise ValueError("표시 이름은 50자 이하여야 합니다")
        except ValueError as e:
            raise Problem(422, "validation_error", str(e), errors=[{"field": "display_name", "message": str(e)}]) from None
        if name != member.display_name:
            before["display_name"], after["display_name"] = member.display_name, name
            member.display_name, member.display_name_key = name, key
    if patch.email is not None:
        if member.is_admin:  # 운영자 계정 장악 방지 — 운영자의 이메일은 CLI 로(§4.7)
            raise Problem(403, "target_is_admin", "운영자의 이메일은 바꿀 수 없습니다")
        try:
            email = checked_email(patch.email)
        except ValueError as e:
            raise Problem(422, "validation_error", str(e), errors=[{"field": "email", "message": str(e)}]) from None
        if email != member.email:
            before["email"], after["email"] = mask_email(member.email or ""), mask_email(email)
            member.email = email
    if patch.is_admin is not None and patch.is_admin != member.is_admin:
        if not patch.is_admin and member.id in admins and len(admins) <= 1:
            raise Problem(409, "last_admin", "마지막 운영자는 해제할 수 없습니다 — 다른 운영자를 먼저 지정해 주세요")
        before["is_admin"], after["is_admin"] = member.is_admin, patch.is_admin
        member.is_admin = patch.is_admin
        await shrink_sessions(db, member.id, patch.is_admin)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise Problem(409, "member_conflict", "같은 이메일이나 표시 이름의 회원이 있습니다") from None
    if after:
        await record(db, viewer, [LogEntry("member.update", "member", member.id, before=before, after=after, reason=patch.reason)])
    return await member_detail(db, member.id)


async def revoke_member_sessions(db: AsyncSession, viewer: Viewer, member_id: int, password: str, reason: str | None) -> int:
    """강제 로그아웃(§4.13 재확인)"""
    await reauth(db, viewer, password)
    member = await _active(db, member_id)
    count = (
        await db.execute(
            select(func.count()).select_from(LoginSession).where(LoginSession.member_id == member.id, LoginSession.revoked_at.is_(None))
        )
    ).scalar_one()
    await sessions.revoke_all(db, member.id)
    await record(db, viewer, [LogEntry("member.revoke_sessions", "member", member.id, after={"sessions": count}, reason=reason)])
    return count
