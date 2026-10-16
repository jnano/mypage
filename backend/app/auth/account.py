"""내 계정·재확인·탈퇴·재설정 — 인증 설계도 §4.5~§4.9·§4.11·§4.13.

재확인(§4.13): 그 폼의 비밀번호를 같은 요청 안에서 검증한다. 해시 **전에** auth.reauth(회원 기준 15분 5회)를 센다 —
세션을 훔친 사람이 이 폼으로 비밀번호를 추측하지 못하게. 운영자의 재확인 실패는 운영 기록에 남긴다(별도 커밋 —
본 요청이 실패로 되돌려져도 남게).
"""

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, exists, literal_column, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.logs import LogEntry, record
from app.auth import keys, sessions
from app.auth.emails import mask_email
from app.auth.login import argon2
from app.auth.passwords import hash_password, problems, verify_password
from app.auth.signup import load_signup
from app.auth.viewer import Viewer, active_sanction_clause
from app.core import rate_limit
from app.core.config import settings
from app.core.invalidation import tags_for
from app.core.outbox import enqueue_revalidate
from app.core.problems import Problem
from app.db.session import SessionLocal
from app.models import (
    Board,
    BoardAccess,
    Comment,
    LevelRequest,
    LoginSession,
    Member,
    MemberGroupMember,
    MemberSanction,
    PasswordResetToken,
    Post,
    WithdrawnEmailMark,
)

WITHDRAWN_NAME = "탈퇴 회원"


def require_member(viewer: Viewer) -> int:
    if viewer.member_id is None:
        raise Problem(401, "login_required", "로그인이 필요합니다")
    return viewer.member_id


async def reauth(db: AsyncSession, viewer: Viewer, password: str) -> Member:
    """비밀번호 재확인 — 맞으면 그 회원(잠그지 않음). 틀리면 403 reauth_failed"""
    member_id = require_member(viewer)
    await rate_limit.hit("auth.reauth", f"m:{member_id}")
    member = await db.get(Member, member_id)
    if member is None or member.password_hash is None:
        raise Problem(401, "login_required", "로그인이 필요합니다")
    if not await argon2(verify_password, member.password_hash, password):
        if viewer.is_admin:
            async with SessionLocal() as log_db, log_db.begin():
                await record(log_db, viewer, [LogEntry("member.reauth_failed", "member", member_id)])
        raise Problem(403, "reauth_failed", "비밀번호가 맞지 않습니다", errors=[{"field": "password", "message": "비밀번호가 맞지 않습니다"}])
    return member


async def _new_password(db: AsyncSession, password: str, field: str = "new_password") -> str:
    if errors := problems(password, (await load_signup(db)).password_min_length):
        raise Problem(422, "validation_error", "비밀번호 규칙에 맞지 않습니다", errors=[{"field": field, "message": m} for m in errors])
    return await argon2(hash_password, password)


# ── 내 계정(§4.5·§4.6) ──────────────────────────────────────


async def account(db: AsyncSession, viewer: Viewer) -> dict[str, Any]:
    member = await db.get(Member, require_member(viewer))
    assert member is not None
    return {
        "email": member.email,
        "display_name": member.display_name,
        "level": member.level,
        "is_admin": member.is_admin,
        "created_at": member.created_at.isoformat(),
        "password_changed_at": member.password_changed_at.isoformat() if member.password_changed_at else None,
        "privacy_version": member.privacy_version,
    }


async def change_password(db: AsyncSession, viewer: Viewer, current: str, new: str) -> None:
    """현재 비밀번호 재확인 → 새 해시 → 이 세션을 뺀 나머지 폐기(§4.6)"""
    member = await reauth(db, viewer, current)
    member.password_hash = await _new_password(db, new)
    member.password_changed_at = datetime.now(UTC)
    await sessions.revoke_all(db, member.id, except_id=viewer.session_id)
    await db.flush()


async def list_sessions(db: AsyncSession, viewer: Viewer) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(LoginSession)
            .where(
                LoginSession.member_id == require_member(viewer),
                LoginSession.revoked_at.is_(None),
                LoginSession.expires_at > datetime.now(UTC),
            )
            .order_by(LoginSession.last_write_at.desc())
        )
    ).scalars()
    return [
        {
            "id": s.id,
            "user_agent": s.user_agent,
            "created_at": s.created_at.isoformat(),
            "last_write_at": s.last_write_at.isoformat(),  # 마지막 활동(글쓰기 등) — 읽기로는 갱신하지 않는다
            "expires_at": s.expires_at.isoformat(),
            "persistent": s.persistent,
            "current": s.id == viewer.session_id,
        }
        for s in rows
    ]


async def revoke_session(db: AsyncSession, viewer: Viewer, session_id: int) -> None:
    """기기 하나 폐기 — 본인 세션만(남의 id 는 없는 것과 같다, IDOR)"""
    result = await db.execute(
        update(LoginSession)
        .where(
            LoginSession.id == session_id,
            LoginSession.member_id == require_member(viewer),
            LoginSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    if not result.rowcount:
        raise Problem(404, "session_not_found", "그 기기를 찾을 수 없습니다")


# ── 운영자 보호(§4.11) ──────────────────────────────────────


async def lock_admins(db: AsyncSession) -> list[int]:
    """운영자 수를 줄일 수 있는 모든 경로가 거친다 — id 순으로 잠가 교착을 막는다(READ COMMITTED 는 대기 뒤 다시 평가)"""
    return list(
        (
            await db.execute(
                select(Member.id)
                .where(Member.is_admin, Member.status == literal_column("'active'"))
                .order_by(Member.id)
                .with_for_update()
            )
        ).scalars()
    )


# ── 탈퇴(§4.9) ──────────────────────────────────────────────


async def withdraw_member(db: AsyncSession, actor: Viewer, member: Member, reason: str | None = None) -> None:
    """본인 탈퇴와 강제 탈퇴가 같은 함수. forced = 행위자가 본인이 아님"""
    forced = actor.member_id != member.id
    if member.is_admin:  # 운영자일 때만 운영자 행을 잠근다(일반 회원 탈퇴마다 잠그지 않는다)
        if len(await lock_admins(db)) <= 1:
            raise Problem(409, "last_admin", "마지막 운영자는 탈퇴할 수 없습니다 — 다른 운영자를 먼저 지정해 주세요")
    now = datetime.now(UTC)
    sanctioned = (
        await db.execute(select(exists().where(MemberSanction.member_id == member.id, active_sanction_clause())))
    ).scalar_one()
    if sanctioned and member.email:
        stmt = insert(WithdrawnEmailMark).values(
            email_hmac=keys.email_hmac(member.email), expires_at=now + timedelta(days=settings.withdrawn_mark_days)
        )
        await db.execute(stmt.on_conflict_do_update(index_elements=["email_hmac"], set_={"expires_at": stmt.excluded.expires_at}))
    masked = mask_email(member.email or "")
    member.status = "withdrawn"
    member.withdrawn_at = now
    member.display_name = WITHDRAWN_NAME
    member.email = member.password_hash = member.display_name_key = member.signup_note = None
    member.is_admin = False
    await sessions.revoke_all(db, member.id)
    await db.execute(
        update(LevelRequest)
        .where(LevelRequest.member_id == member.id, LevelRequest.status == literal_column("'pending'"))
        .values(status="cancelled", decided_at=now)
    )
    await db.execute(delete(BoardAccess).where(BoardAccess.subject_type == "member", BoardAccess.subject_id == member.id))
    await db.execute(delete(MemberGroupMember).where(MemberGroupMember.member_id == member.id))  # 그룹 소속도(검토 v4 T-2)
    # 글·댓글: 작성자를 비우고 이름을 '탈퇴 회원'으로(본 설계서 §4.3·§4.4)
    posts = (
        await db.execute(
            update(Post)  # post-clause: exempt — 탈퇴 회원의 글 작성자 정리(조회 아님)
            .where(Post.member_id == member.id)
            .values(member_id=None, author_name_snapshot=WITHDRAWN_NAME)
            .returning(Post.id, Post.board_id)
        )
    ).all()
    comment_posts = (
        await db.execute(
            update(Comment)
            .where(Comment.member_id == member.id)
            .values(member_id=None, author_name_snapshot=WITHDRAWN_NAME)
            .returning(Comment.post_id)
        )
    ).scalars()
    slugs = dict((await db.execute(select(Board.id, Board.slug).where(Board.id.in_({p.board_id for p in posts})))).all()) if posts else {}
    await enqueue_revalidate(
        db,
        [tags_for("member.withdrawn.post", post_id=p.id, board_slug=slugs[p.board_id]) for p in posts]
        + [tags_for("member.withdrawn.comment", post_id=pid) for pid in set(comment_posts)],
    )
    await db.flush()
    if forced:
        await record(db, actor, [LogEntry("member.withdraw", "member", member.id, before={"email": masked}, reason=reason)])


async def withdraw_self(db: AsyncSession, viewer: Viewer, password: str) -> None:
    member = await reauth(db, viewer, password)
    await withdraw_member(db, viewer, member)


async def _target(db: AsyncSession, member_id: int) -> Member:
    member = (
        await db.execute(
            select(Member).where(Member.id == member_id, Member.status == literal_column("'active'")).with_for_update()
        )
    ).scalar_one_or_none()
    if member is None:
        raise Problem(404, "member_not_found", "활동 회원을 찾을 수 없습니다")
    return member


async def force_withdraw(db: AsyncSession, viewer: Viewer, member_id: int, password: str, reason: str) -> None:
    """강제 탈퇴(운영자) — 재확인, 사유 필수. 대상이 운영자면 먼저 운영자 해제(§4.9)"""
    await reauth(db, viewer, password)
    member = await _target(db, member_id)
    if member.is_admin:
        raise Problem(403, "target_is_admin", "운영자는 강제 탈퇴할 수 없습니다 — 먼저 운영자를 해제해 주세요")
    await withdraw_member(db, viewer, member, reason)


# ── 재설정 링크(§4.8, 메일 없는 동안) ───────────────────────


async def issue_reset_link(db: AsyncSession, viewer: Viewer, member_id: int, password: str) -> dict[str, Any]:
    """24시간·1회 토큰. 링크는 /reset#t=<토큰> — URL 조각은 서버·접근 로그·Referer 에 가지 않는다"""
    await reauth(db, viewer, password)
    member = await _target(db, member_id)
    if member.is_admin:
        raise Problem(403, "target_is_admin", "운영자 계정은 재설정 링크를 받을 수 없습니다 — 서버 CLI 로 복구합니다")
    now = datetime.now(UTC)
    await db.execute(  # 이전 미사용 토큰은 막는다
        update(PasswordResetToken)
        .where(PasswordResetToken.member_id == member.id, PasswordResetToken.used_at.is_(None))
        .values(used_at=now)
    )
    token = secrets.token_urlsafe(32)
    expires_at = now + timedelta(hours=settings.reset_token_hours)
    db.add(PasswordResetToken(token_hash=sessions.hash_token(token), member_id=member.id, created_by=viewer.member_id, expires_at=expires_at))
    await record(db, viewer, [LogEntry("member.reset_link", "member", member.id, after={"email": mask_email(member.email or "")})])
    await db.flush()
    return {"path": f"/reset#t={token}", "expires_at": expires_at.isoformat()}


async def use_reset_link(db: AsyncSession, token: str, new_password: str, ip: str) -> None:
    """회원이 링크로 새 비밀번호 — 토큰 사용 → 세션 전부 폐기 → 다음 로그인 때 안내(§4.8-2)"""
    await rate_limit.hit("auth.reset", ip)  # 토큰 기준은 추측마다 키가 바뀌어 효과가 없다
    now = datetime.now(UTC)
    row = (
        await db.execute(
            select(PasswordResetToken, Member)
            .join(Member, Member.id == PasswordResetToken.member_id)
            .where(
                PasswordResetToken.token_hash == sessions.hash_token(token),
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.expires_at > now,
                Member.status == literal_column("'active'"),
                Member.is_admin.is_(False),
            )
            .with_for_update(of=PasswordResetToken)
        )
    ).one_or_none()
    if row is None:
        raise Problem(410, "reset_link_invalid", "링크가 만료되었거나 이미 쓰였습니다. 운영자에게 새 링크를 받아 주세요")
    reset, member = row
    member.password_hash = await _new_password(db, new_password, field="password")
    member.password_changed_at = member.password_reset_by_admin_at = now
    reset.used_at = now
    await sessions.revoke_all(db, member.id)
    await db.flush()


