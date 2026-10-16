"""always 모드 조회수 버퍼 — 설계도 §6.1. API 프로세스 메모리에 더하고 30초마다 한 문장으로 반영한다.

작업자가 아니라 API 프로세스의 lifespan 배경 작업이 비운다(버퍼가 이 프로세스 메모리에 있다).
더하기만 하므로 프로세스가 여러 개여도 합계가 맞다. 정상 종료 때 한 번 더 비운다 — 잃는 양은 비정상 종료 때 최대 30초분.
"""

import asyncio
import logging
from collections import Counter

from sqlalchemy import Integer, column, update, values
from sqlalchemy.dialects.postgresql import BIGINT

from app.db.session import SessionLocal
from app.models import PostStat

logger = logging.getLogger(__name__)

INTERVAL_SEC = 30
MAX_ATTEMPTS = 3  # 반영이 연달아 실패하면 버린다 — 메모리가 끝없이 늘지 않게

_pending: Counter[int] = Counter()
_attempts = 0


def add(post_id: int) -> None:
    _pending[post_id] += 1


def pending() -> dict[int, int]:
    return dict(_pending)


async def flush() -> int:
    """버퍼를 비워 반영한다. 반영한 글 수. 실패하면 버퍼에 되돌린다(MAX_ATTEMPTS 회까지)."""
    global _attempts
    if not _pending:
        return 0
    batch = sorted(_pending.items())  # post_id 순 — 여러 프로세스가 같은 행들을 같은 순서로 잠근다
    _pending.clear()
    v = values(column("id", BIGINT), column("n", Integer), name="v").data(batch)
    stmt = update(PostStat).where(PostStat.post_id == v.c.id).values(view_count=PostStat.view_count + v.c.n)
    try:
        async with SessionLocal() as db, db.begin():
            await db.execute(stmt)
    except Exception:
        _attempts += 1
        if _attempts >= MAX_ATTEMPTS:
            logger.warning("조회수 버퍼 반영이 %d번 실패해 %d개 글의 조회를 버립니다", _attempts, len(batch))
            _attempts = 0
        else:
            logger.exception("조회수 버퍼 반영 실패 — 다음 차례에 다시")
            _pending.update(dict(batch))
        return 0
    _attempts = 0
    return len(batch)


async def run_forever() -> None:
    while True:
        await asyncio.sleep(INTERVAL_SEC)
        await flush()
