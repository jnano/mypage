"""사이트 설정·재색인·실패 작업 API — 설계도 §14.3. 운영자 전용."""

from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin import settings as site_settings
from app.admin.logs import LogEntry, record
from app.admin.scope import StaffScope
from app.api.admin_boards import admin_scope
from app.core import outbox
from app.core.invalidation import tags_for
from app.core.problems import Problem
from app.db.session import SessionLocal, get_db
from app.models import OutboxEvent

router = APIRouter(prefix="/admin")

JOB_PAGE = 100


def _group(group: str) -> str:
    if group not in site_settings.GROUPS:
        raise Problem(404, "setting_group_not_found", "없는 설정 묶음입니다")
    return group


@router.get("/settings/{group}")
async def get_settings(group: str, scope: StaffScope = Depends(admin_scope), db: AsyncSession = Depends(get_db)):
    return {"group": group, "value": (await site_settings.load(db, _group(group))).model_dump()}


@router.patch("/settings/{group}")
async def patch_settings(
    group: str,
    body: dict[str, Any] = Body(...),
    reason: str | None = Query(None, max_length=500),
    scope: StaffScope = Depends(admin_scope),
):
    """보낸 칸만 바꾼다. 형식 검증은 묶음별 Pydantic 모델(app.admin.settings.GROUPS)."""
    async with SessionLocal() as db, db.begin():
        value = await site_settings.save(db, scope.viewer, _group(group), body, reason)
    return {"group": group, "value": value.model_dump(), "invalidate": tags_for("settings.updated", group=group).as_dict()}


@router.post("/search/reindex", status_code=202)
async def reindex(scope: StaffScope = Depends(admin_scope)):
    """전체 재색인 — 작업자가 묶음(500글)마다 이어서 돈다(search.reindex)."""
    async with SessionLocal() as db, db.begin():
        running = (
            await db.execute(
                select(OutboxEvent.id).where(OutboxEvent.type == "search.reindex", OutboxEvent.processed_at.is_(None), OutboxEvent.dead_at.is_(None)).limit(1)
            )
        ).scalar_one_or_none()
        if running is not None:
            raise Problem(409, "reindex_running", "재색인이 이미 진행 중입니다")
        await outbox.enqueue(db, [outbox.Event("search.reindex", {"after_id": 0, "done": 0})])
        await record(db, scope.viewer, [LogEntry("search.reindex", "setting", 0)])
    return {"queued": True}


@router.get("/jobs")
async def jobs(status: str = Query("dead"), scope: StaffScope = Depends(admin_scope), db: AsyncSession = Depends(get_db)):
    """실패 작업(dead) 목록 — 또는 status=pending 으로 밀린 작업."""
    stmt = select(OutboxEvent).order_by(OutboxEvent.id.desc()).limit(JOB_PAGE)
    if status == "pending":
        stmt = stmt.where(OutboxEvent.processed_at.is_(None), OutboxEvent.dead_at.is_(None))
    else:
        stmt = stmt.where(OutboxEvent.dead_at.is_not(None))
    rows = (await db.execute(stmt)).scalars().all()
    counts = (
        await db.execute(
            select(
                func.count().filter(OutboxEvent.dead_at.is_not(None)).label("dead"),
                func.count().filter(OutboxEvent.processed_at.is_(None), OutboxEvent.dead_at.is_(None)).label("pending"),
            )
        )
    ).one()
    return {
        "counts": {"dead": counts.dead, "pending": counts.pending},
        "items": [
            {
                "id": e.id,
                "type": e.type,
                "payload": e.payload,
                "attempts": e.attempts,
                "last_error": e.last_error,
                "available_at": e.available_at.isoformat(),
                "dead_at": e.dead_at.isoformat() if e.dead_at else None,
                "created_at": e.created_at.isoformat(),
            }
            for e in rows
        ],
    }


@router.post("/jobs/{event_id}/retry")
async def retry_job(event_id: int, scope: StaffScope = Depends(admin_scope)):
    """실패 작업을 다시 시도 — 횟수를 0으로, 바로 처리 대상으로."""
    async with SessionLocal() as db, db.begin():
        done = (
            await db.execute(
                update(OutboxEvent)
                .where(OutboxEvent.id == event_id, OutboxEvent.dead_at.is_not(None))
                .values(dead_at=None, attempts=0, available_at=func.now(), last_error=None)
                .returning(OutboxEvent.type)
            )
        ).scalar_one_or_none()
        if done is None:
            raise Problem(404, "job_not_found", "실패 작업을 찾을 수 없습니다")
        await db.execute(select(func.pg_notify(outbox.CHANNEL, "")))
        await record(db, scope.viewer, [LogEntry("job.retry", "setting", event_id, after={"type": done})])
    return {"retried": True}
