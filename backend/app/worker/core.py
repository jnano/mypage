"""outbox 처리 — 설계도 §3.2.

이벤트 하나 = 트랜잭션 하나: `FOR UPDATE SKIP LOCKED` 로 꺼내 → 처리기(SAVEPOINT 안) → processed_at.
처리기의 DB 변경과 처리 완료 표시가 같은 커밋이라, 커밋 전에 죽으면 다른 작업자가 다시 줍는다(멱등은 처리기·dedupe_key 몫).
처리기가 실패하면 SAVEPOINT 만 되돌리고, 같은 트랜잭션에서 attempts+1·지수 백오프·last_error 를 남긴다. 5회면 dead_at.
고정 조건은 부분 인덱스 ix_outbox_events_pending 의 조건과 같은 모양(processed_at IS NULL AND dead_at IS NULL).
"""

import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionLocal
from app.models import OutboxEvent

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
BACKOFF_BASE_SECONDS = 2  # 2, 4, 8, 16초 … 뒤 다시
BACKOFF_CAP_SECONDS = 600

Handler = Callable[[AsyncSession, OutboxEvent], Awaitable[None]]
HANDLERS: dict[str, Handler] = {}


def handles(event_type: str) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        if event_type in HANDLERS:
            raise ValueError(f"처리기가 이미 있습니다: {event_type}")
        HANDLERS[event_type] = fn
        return fn

    return register


def backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(BACKOFF_CAP_SECONDS, BACKOFF_BASE_SECONDS**attempts))


async def process_one() -> bool:
    """처리할 이벤트가 있었으면 True."""
    async with SessionLocal() as db, db.begin():
        event = (
            await db.execute(
                select(OutboxEvent)
                .where(
                    OutboxEvent.processed_at.is_(None),
                    OutboxEvent.dead_at.is_(None),
                    OutboxEvent.available_at <= func.now(),
                )
                .order_by(OutboxEvent.available_at, OutboxEvent.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if event is None:
            return False
        try:
            handler = HANDLERS.get(event.type)
            if handler is None:
                raise LookupError(f"처리기가 없는 이벤트: {event.type}")
            async with db.begin_nested():
                await handler(db, event)
            event.processed_at = func.now()
        except Exception as e:  # 처리기 실패는 기록하고 다음 기회에(작업자는 멈추지 않는다)
            event.attempts += 1
            event.last_error = f"{type(e).__name__}: {e}"[:2000]
            if event.attempts >= MAX_ATTEMPTS:
                event.dead_at = func.now()
                logger.error("outbox %s(%s) 실패 %d회 — dead", event.id, event.type, event.attempts)
            else:
                event.available_at = func.now() + backoff(event.attempts)
                logger.warning("outbox %s(%s) 실패 %d회: %s", event.id, event.type, event.attempts, e)
        return True


async def process_available(limit: int) -> int:
    done = 0
    while done < limit and await process_one():
        done += 1
    return done
