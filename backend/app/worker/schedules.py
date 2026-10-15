"""주기 작업 일정 — worker_schedules 표(§4.5). 작업자가 여럿이어도 한 작업은 한 번에 한 곳에서만 돈다.

선점: 기한이 된 행 하나를 FOR UPDATE SKIP LOCKED 로 골라 locked_until 을 걸고 커밋 → 작업(자기 트랜잭션) →
last_run_at·next_run_at 을 적고 잠금을 푼다. 작업이 실패해도 다음 주기에 다시 돈다(locked_until 이 지나면 다른 작업자도).
"""

import logging

from sqlalchemy import func, literal_column, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert

from app.db.session import SessionLocal
from app.models import WorkerSchedule
from app.worker.jobs import JOBS

logger = logging.getLogger(__name__)

LOCK_FOR = text("interval '10 minutes'")


async def ensure_schedules() -> None:
    """알려진 작업의 행을 만들고 주기를 코드와 맞춘다. 처음 만든 작업은 바로 한 번 돈다(next_run_at 기본값 now())."""
    if not JOBS:
        return
    async with SessionLocal() as db, db.begin():
        stmt = insert(WorkerSchedule).values(
            [{"name": j.name, "interval_sec": j.interval_sec} for j in JOBS.values()]
        )
        await db.execute(
            stmt.on_conflict_do_update(index_elements=["name"], set_={"interval_sec": stmt.excluded.interval_sec})
        )


async def run_due_one() -> str | None:
    """기한이 된 작업 하나를 돌린다. 돌린 작업 이름(없으면 None)."""
    async with SessionLocal() as db, db.begin():
        name = (
            await db.execute(
                select(WorkerSchedule.name)
                .where(
                    WorkerSchedule.name.in_(list(JOBS)),
                    WorkerSchedule.next_run_at <= func.now(),
                    or_(WorkerSchedule.locked_until.is_(None), WorkerSchedule.locked_until < func.now()),
                )
                .order_by(WorkerSchedule.next_run_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if name is None:
            return None
        await db.execute(
            update(WorkerSchedule).where(WorkerSchedule.name == name).values(locked_until=func.now() + LOCK_FOR)
        )

    job = JOBS[name]
    try:
        async with SessionLocal() as db, db.begin():
            count = await job.run(db)
        logger.info("주기 작업 %s: %d건", name, count)
    except Exception:
        logger.exception("주기 작업 %s 실패 — 다음 주기에 다시", name)
    finally:
        async with SessionLocal() as db, db.begin():
            await db.execute(
                update(WorkerSchedule)
                .where(WorkerSchedule.name == name)
                .values(
                    last_run_at=func.now(),
                    next_run_at=func.now() + func.make_interval(0, 0, 0, 0, 0, 0, literal_column(str(job.interval_sec))),
                    locked_until=None,
                )
            )
    return name
