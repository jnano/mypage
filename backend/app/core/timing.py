"""요청 계측 — 설계도 §15.3. 요청당 서버 내부 시간·DB 시간·쿼리 수를 표준 Server-Timing 헤더로 낸다.

SERVER_TIMING=true 일 때만 켠다(기본 끔 — 운영에서 내부 시간을 밖에 보이지 않게).
DB 시간은 SQLAlchemy 공식 이벤트(before/after_cursor_execute)로 잰다. 요청 밖(작업자 등)의 쿼리는 세지 않는다.
연결 풀은 공식 풀 이벤트(checkout)로 꺼낸 직후의 사용 중 연결 수 최고치를 싣는다. 풀에는 '꺼내기 전' 이벤트가 없어
대기 시간을 직접 재지 못한다 — QueuePool 은 연결이 모두 쓰이는 중일 때만 기다리므로, 최고치 < 용량이면 대기는 0 이다.
"""

import time
from contextvars import ContextVar
from dataclasses import dataclass

from fastapi import FastAPI, Request
from sqlalchemy import event
from starlette.responses import Response

from app.core.config import settings
from app.db.session import engine


@dataclass
class _Acc:
    queries: int = 0
    db_seconds: float = 0.0
    pool_peak: int = 0


_current: ContextVar[_Acc | None] = ContextVar("request_timing", default=None)
_START = "timing_query_start"


def _before(conn, _cursor, _statement, _parameters, _context, _executemany) -> None:
    conn.info.setdefault(_START, []).append(time.perf_counter())


def _after(conn, _cursor, _statement, _parameters, _context, _executemany) -> None:
    started = conn.info[_START].pop()
    acc = _current.get()
    if acc is not None:
        acc.queries += 1
        acc.db_seconds += time.perf_counter() - started


def _checkout(_dbapi_conn, _record, _proxy) -> None:
    acc = _current.get()
    if acc is not None:
        acc.pool_peak = max(acc.pool_peak, engine.sync_engine.pool.checkedout())


def _capacity() -> int:
    return settings.db_pool_size + settings.db_max_overflow


def install(app: FastAPI) -> None:
    event.listen(engine.sync_engine, "before_cursor_execute", _before)
    event.listen(engine.sync_engine, "after_cursor_execute", _after)
    event.listen(engine.sync_engine.pool, "checkout", _checkout)

    @app.middleware("http")
    async def server_timing(request: Request, call_next) -> Response:
        acc = _Acc()
        token = _current.set(acc)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            _current.reset(token)
        app_ms = (time.perf_counter() - started) * 1000
        response.headers["Server-Timing"] = (
            f'app;dur={app_ms:.2f}, db;dur={acc.db_seconds * 1000:.2f};desc="q={acc.queries}", '
            f'pool;desc="peak={acc.pool_peak}/{_capacity()}"'
        )
        return response


def uninstall() -> None:
    """이벤트 훅을 뗀다(테스트용). 미들웨어는 앱과 함께 사라진다."""
    event.remove(engine.sync_engine, "before_cursor_execute", _before)
    event.remove(engine.sync_engine, "after_cursor_execute", _after)
    event.remove(engine.sync_engine.pool, "checkout", _checkout)
