"""outbox — 본 데이터와 같은 트랜잭션에 작업을 넣는다(§3.1-5, §3.2).

여러 행은 INSERT … VALUES 한 번. NOTIFY 는 PostgreSQL 이 같은 트랜잭션의 같은 알림을 하나로 접는다.
처리는 작업자(app/worker, `python -m app.worker`).
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.invalidation import Invalidation
from app.models import OutboxEvent

CHANNEL = "outbox"


@dataclass(frozen=True)
class Event:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    dedupe_key: str | None = None
    available_at: datetime | None = None  # 미래면 예약 작업


async def enqueue(db: AsyncSession, events: list[Event]) -> None:
    if not events:
        return
    rows = []
    for e in events:
        row: dict[str, Any] = {"type": e.type, "payload": e.payload, "dedupe_key": e.dedupe_key}
        if e.available_at is not None:
            row["available_at"] = e.available_at
        rows.append(row)
    if any("available_at" in r for r in rows):
        for r in rows:
            r.setdefault("available_at", func.now())
    await db.execute(insert(OutboxEvent).values(rows))
    await db.execute(select(func.pg_notify(CHANNEL, "")))


async def enqueue_revalidate(db: AsyncSession, invalidations: list[Invalidation]) -> None:
    """작업자가 바꾼 데이터의 캐시 무효화를 같은 트랜잭션에 예약한다(§3.4 '작업자 변경').
    태그는 무효화 표(core.invalidation)에서 정한 것을 모아 한 이벤트로. 실패하면 작업자 재시도를 탄다."""
    # 집합으로 모은다(순서는 처음 나온 순) — 탈퇴처럼 글이 많으면 게시판·recent 태그가 글마다 되풀이된다(검토 v4 T-1)
    now = dict.fromkeys(t for inv in invalidations for t in inv.now)
    later = dict.fromkeys(t for inv in invalidations for t in inv.max if t not in now)
    if now or later:
        await enqueue(db, [Event("cache.revalidate", {"now": list(now), "max": list(later)})])
