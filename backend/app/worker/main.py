"""작업자 고리 — 설계도 §3.2. API 와 다른 프로세스(systemd 서비스, §17).

깨어나는 이유: ① LISTEN outbox 알림(풀 밖의 전용 asyncpg 연결) ② 폴링(놓친 알림·예약 작업·주기 작업, WORKER_POLL_SECONDS).
깨어나면: outbox 를 batch 만큼 처리 → 기한이 된 주기 작업을 모두 돌림 → 다시 기다림.
"""

import asyncio
import contextlib
import logging

import asyncpg
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.core.outbox import CHANNEL
from app.worker import handlers  # noqa: F401 — 처리기 등록
from app.worker.core import process_available
from app.worker.schedules import ensure_schedules, run_due_one

logger = logging.getLogger(__name__)


def _asyncpg_dsn() -> str:
    return make_url(settings.database_url).set(drivername="postgresql").render_as_string(hide_password=False)


class Listener:
    """LISTEN 전용 연결. 끊기면 다음 고리에서 다시 잇는다(그동안은 폴링이 받친다)."""

    def __init__(self, wake: asyncio.Event) -> None:
        self.wake = wake
        self.conn: asyncpg.Connection | None = None

    def _on_notify(self, *_args) -> None:
        self.wake.set()

    async def ensure(self) -> None:
        if self.conn is not None and not self.conn.is_closed():
            return
        try:
            self.conn = await asyncpg.connect(_asyncpg_dsn())
            await self.conn.add_listener(CHANNEL, self._on_notify)
            self.wake.set()  # 다시 잇는 사이에 온 일을 줍는다
        except (OSError, asyncpg.PostgresError) as e:
            logger.warning("LISTEN 연결 실패 — 폴링으로 계속: %s", e)
            self.conn = None

    async def close(self) -> None:
        if self.conn is not None and not self.conn.is_closed():
            await self.conn.close()


async def run(stop: asyncio.Event, *, poll_seconds: float | None = None) -> None:
    poll = poll_seconds if poll_seconds is not None else settings.worker_poll_seconds
    wake = asyncio.Event()
    listener = Listener(wake)
    await ensure_schedules()
    logger.info("작업자 시작(폴링 %.0f초)", poll)
    try:
        while not stop.is_set():
            await listener.ensure()
            wake.clear()
            processed = await process_available(settings.worker_batch)
            while await run_due_one():
                pass
            if processed >= settings.worker_batch:
                continue  # 밀린 일이 더 있다
            waits = [asyncio.create_task(wake.wait()), asyncio.create_task(stop.wait())]
            await asyncio.wait(waits, timeout=poll, return_when=asyncio.FIRST_COMPLETED)
            for t in waits:
                t.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await t
    finally:
        await listener.close()
        logger.info("작업자 종료")
