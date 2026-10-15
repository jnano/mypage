"""요청 계측(§15.3) — Server-Timing 헤더의 쿼리 수·DB 시간."""

import re

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timing
from app.db.session import get_db

pytestmark = pytest.mark.anyio


async def test_server_timing_counts_queries() -> None:
    app = FastAPI()
    timing.install(app)

    @app.get("/three")
    async def three(db: AsyncSession = Depends(get_db)) -> dict:
        for _ in range(3):
            await db.execute(text("SELECT 1"))
        return {}

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            header = (await c.get("/three")).headers["server-timing"]
    finally:
        timing.uninstall()
    m = re.fullmatch(r'app;dur=([\d.]+), db;dur=([\d.]+);desc="q=(\d+)", pool;desc="peak=(\d+)/(\d+)"', header)
    assert m and m.group(3) == "3" and float(m.group(1)) >= float(m.group(2)) > 0
    # 연결 하나를 썼다 — 풀 최고치는 1 이상, 용량은 설정값
    assert 1 <= int(m.group(4)) <= int(m.group(5))


async def test_off_by_default(client: AsyncClient) -> None:
    assert "server-timing" not in (await client.get("/api/health")).headers
