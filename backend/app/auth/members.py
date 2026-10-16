"""가입 승인·거부(운영자) — 인증 설계도 §4.2. 운영 기록에는 이메일 원문을 넣지 않는다(가린 값만, §3.8)."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, exists, literal_column, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.logs import LogEntry, record
from app.auth import keys
from app.auth.emails import mask_email
from app.auth.names import clean_display_name, display_name_key
from app.auth.signup import load_signup
from app.auth.viewer import Viewer
from app.core.problems import Problem
from app.models import Member, WithdrawnEmailMark


def _name_taken() -> Problem:
    return Problem(409, "display_name_taken", "같은 표시 이름의 회원이 있습니다 — 이름을 고친 뒤 승인해 주세요")


async def list_pending(db: AsyncSession) -> list[dict[str, Any]]:
    """가입 대기열 — 이메일·표시 이름·자기소개·신청 시각·'최근 제재 중 탈퇴한 주소' 표시"""
    rows = (
        await db.execute(
            select(Member.id, Member.email, Member.display_name, Member.signup_note, Member.created_at)
            .where(Member.status == literal_column("'pending'"))
            .order_by(Member.created_at, Member.id)
            .limit(500)
        )
    ).all()
    marks: set[bytes] = set()
    if rows:
        hmacs = [keys.email_hmac(r.email or "") for r in rows]
        marks = set(
            (
                await db.execute(
                    select(WithdrawnEmailMark.email_hmac).where(
                        WithdrawnEmailMark.email_hmac.in_(hmacs), WithdrawnEmailMark.expires_at > datetime.now(UTC)
                    )
                )
            ).scalars()
        )
    return [
        {
            "id": r.id,
            "email": r.email,
            "display_name": r.display_name,
            "signup_note": r.signup_note,
            "created_at": r.created_at.isoformat(),
            "recently_withdrawn_under_sanction": keys.email_hmac(r.email or "") in marks,
        }
        for r in rows
    ]


async def approve(db: AsyncSession, viewer: Viewer, member_id: int, display_name: str | None) -> dict[str, Any]:
    member = (
        await db.execute(
            select(Member).where(Member.id == member_id, Member.status == literal_column("'pending'")).with_for_update()
        )
    ).scalar_one_or_none()
    if member is None:
        raise Problem(404, "member_not_found", "대기 중인 가입 신청이 없습니다")
    if display_name is not None:  # 운영자가 신청자의 표시 이름을 고친 뒤 승인
        try:
            member.display_name = clean_display_name(display_name)[:50]
            member.display_name_key = display_name_key(member.display_name)
        except ValueError as e:
            raise Problem(422, "validation_error", str(e)) from None
    # 안내용 확인 — 최종 판정은 부분 UNIQUE(동시에 두 운영자가 같은 키를 승인하면 하나만 성공, 검토 v2 C-7)
    if (
        await db.execute(
            select(
                exists().where(
                    Member.display_name_key == member.display_name_key,
                    Member.status == literal_column("'active'"),
                    Member.id != member.id,
                )
            )
        )
    ).scalar_one():
        raise _name_taken()
    level = (await load_signup(db)).default_level
    member.status = "active"
    member.level = level
    member.approved_at = datetime.now(UTC)
    member.approved_by = viewer.member_id
    member.signup_note = None  # 판단 정보는 승인 뒤 지운다(§0) — 운영 기록에도 싣지 않는다
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise _name_taken() from None
    await record(
        db,
        viewer,
        [
            LogEntry(
                "member.approve", "member", member.id,
                after={"email": mask_email(member.email or ""), "display_name": member.display_name, "level": level},
            )
        ],
    )  # fmt: skip
    return {"id": member.id, "status": "active", "level": level}


async def reject(db: AsyncSession, viewer: Viewer, member_ids: list[int], reason: str | None) -> int:
    """거부 — 행을 지운다(글이 없다). 여러 건"""
    rows = (
        await db.execute(
            delete(Member)
            .where(Member.id.in_(member_ids), Member.status == literal_column("'pending'"))
            .returning(Member.id, Member.email)
        )
    ).all()
    await record(
        db,
        viewer,
        [LogEntry("member.reject", "member", r.id, before={"email": mask_email(r.email or "")}, reason=reason) for r in rows],
    )
    return len(rows)


async def purge_stale_pending(db: AsyncSession, days: int = 30) -> int:
    """30일 지난 가입 대기 삭제(§8 — 작업자의 정리 작업이 부른다)"""
    result = await db.execute(
        delete(Member).where(
            Member.status == literal_column("'pending'"), Member.created_at < datetime.now(UTC) - timedelta(days=days)
        )
    )
    return result.rowcount or 0
