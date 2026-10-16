"""레벨 승급 신청 — 인증 설계도 §4.10. 회원이 신청하고 운영자가 승인·거부한다(담당자 아님 — 사이트 전체 일).

승인 트랜잭션: 회원 행 FOR UPDATE → 지금 레벨이 신청 때(from_level)와 다르면 그 신청을 cancelled('그 사이 레벨이 바뀜')로
닫고 **커밋한 뒤** 409 → 같으면 레벨 변경·approved·운영 기록·알림(outbox level.decided).
"""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, literal_column, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin import settings as site_settings
from app.admin.logs import LogEntry, record
from app.admin.settings import LevelNames
from app.auth.account import require_member
from app.auth.viewer import Viewer
from app.core import outbox, rate_limit
from app.core.problems import Problem
from app.models import LevelRequest, Member

PAGE = 100


class LevelRequestBody(BaseModel):
    to_level: int = Field(ge=1, le=99)
    reason: str = Field(max_length=1000)

    @field_validator("reason")
    @classmethod
    def _reason(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("사유를 적어 주세요")
        return v.strip()


class RejectBody(BaseModel):
    note: str = Field(max_length=500)

    @field_validator("note")
    @classmethod
    def _note(cls, v: str) -> str:
        if not v.strip():  # 거부 사유 필수(CHECK 와 같은 뜻)
            raise ValueError("거부 사유를 적어 주세요")
        return v.strip()


async def level_names(db: AsyncSession) -> LevelNames:
    value = await site_settings.load(db, "levels")
    assert isinstance(value, LevelNames)
    return value


def _row(r: LevelRequest) -> dict[str, Any]:
    return {
        "id": r.id,
        "from_level": r.from_level,
        "to_level": r.to_level,
        "reason": r.reason,
        "status": r.status,
        "decision_note": r.decision_note,
        "created_at": r.created_at.isoformat(),
        "decided_at": r.decided_at.isoformat() if r.decided_at else None,
    }


async def my_requests(db: AsyncSession, viewer: Viewer) -> dict[str, Any]:
    member_id = require_member(viewer)
    config = await level_names(db)
    level = (await db.execute(select(Member.level).where(Member.id == member_id))).scalar_one()
    rows = (
        await db.execute(select(LevelRequest).where(LevelRequest.member_id == member_id).order_by(LevelRequest.id.desc()).limit(20))
    ).scalars()
    return {
        "level": level,
        "names": config.names,
        "requestable": [lv for lv in config.requestable if lv > level],
        "items": [_row(r) for r in rows],
    }


async def create_request(db: AsyncSession, viewer: Viewer, body: LevelRequestBody) -> dict[str, Any]:
    member_id = require_member(viewer)
    await rate_limit.hit("level.request", f"m:{member_id}")
    config = await level_names(db)
    level = (await db.execute(select(Member.level).where(Member.id == member_id))).scalar_one()
    if body.to_level not in config.requestable or body.to_level <= level:
        raise Problem(422, "validation_error", "신청할 수 없는 레벨입니다", errors=[{"field": "to_level", "message": "신청할 수 있는 레벨이 아닙니다"}])
    req = LevelRequest(member_id=member_id, from_level=level, to_level=body.to_level, reason=body.reason)
    db.add(req)
    try:
        await db.flush()
    except IntegrityError:  # 한 사람은 한 번에 하나(부분 UNIQUE)
        await db.rollback()
        raise Problem(409, "level_request_pending", "이미 처리를 기다리는 신청이 있습니다") from None
    return _row(req)


async def cancel_request(db: AsyncSession, viewer: Viewer, request_id: int) -> None:
    """본인의 대기 신청만 — 남의 id 는 없는 것과 같다(IDOR)"""
    result = await db.execute(
        update(LevelRequest)
        .where(
            LevelRequest.id == request_id,
            LevelRequest.member_id == require_member(viewer),
            LevelRequest.status == literal_column("'pending'"),
        )
        .values(status="cancelled", decided_at=datetime.now(UTC))
    )
    if not result.rowcount:
        raise Problem(404, "level_request_not_found", "그 신청을 찾을 수 없습니다")


async def queue(db: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(LevelRequest, Member.display_name, Member.level)
            .join(Member, Member.id == LevelRequest.member_id)
            .where(LevelRequest.status == literal_column("'pending'"))
            .order_by(LevelRequest.created_at)
            .limit(PAGE)
        )
    ).all()
    return [_row(r) | {"member_id": r.member_id, "display_name": name, "current_level": lv} for r, name, lv in rows]


async def pending_count(db: AsyncSession) -> int:
    return (
        await db.execute(select(func.count()).select_from(LevelRequest).where(LevelRequest.status == literal_column("'pending'")))
    ).scalar_one()


async def _pending(db: AsyncSession, request_id: int) -> LevelRequest:
    req = (
        await db.execute(
            select(LevelRequest).where(LevelRequest.id == request_id, LevelRequest.status == literal_column("'pending'")).with_for_update()
        )
    ).scalar_one_or_none()
    if req is None:
        raise Problem(404, "level_request_not_found", "처리를 기다리는 신청이 없습니다")
    return req


async def _decided(db: AsyncSession, req: LevelRequest) -> None:
    await outbox.enqueue(db, [outbox.Event("level.decided", {"request_id": req.id})])


async def approve(db: AsyncSession, viewer: Viewer, request_id: int) -> dict[str, Any]:
    """승인 — 그 사이 레벨이 바뀌었으면 신청을 닫아 커밋하고 409(§4.10-3). 호출한 쪽은 성공일 때만 커밋한다"""
    req = await _pending(db, request_id)
    member = (
        await db.execute(
            select(Member).where(Member.id == req.member_id, Member.status == literal_column("'active'")).with_for_update()
        )
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if member is None or member.level != req.from_level:
        req.status, req.decided_by, req.decided_at, req.decision_note = "cancelled", viewer.member_id, now, "그 사이 레벨이 바뀜"
        await _decided(db, req)  # 신청자에게 알린다(검토 v5 U-2)
        await db.commit()
        raise Problem(409, "level_changed", "신청 뒤에 회원의 레벨이 바뀌어 신청을 닫았습니다")
    before = member.level
    member.level = req.to_level
    req.status, req.decided_by, req.decided_at = "approved", viewer.member_id, now
    await record(
        db, viewer,
        [LogEntry("level.approve", "member", member.id, before={"level": before}, after={"level": req.to_level})],
    )  # fmt: skip
    await _decided(db, req)
    await db.flush()
    return _row(req)


async def reject(db: AsyncSession, viewer: Viewer, request_id: int, note: str) -> dict[str, Any]:
    req = await _pending(db, request_id)
    req.status, req.decided_by, req.decided_at, req.decision_note = "rejected", viewer.member_id, datetime.now(UTC), note
    await record(db, viewer, [LogEntry("level.reject", "member", req.member_id, after={"to_level": req.to_level}, reason=note)])
    await _decided(db, req)
    await db.flush()
    return _row(req)
