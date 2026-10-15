"""outbox — 본 데이터와 같은 트랜잭션에 작업을 넣는다(§3.1-5, §3.2).

여러 행은 INSERT … VALUES 한 번, NOTIFY 는 트랜잭션당 한 번. 작업자는 2단계에서 붙는다.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

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
