"""요청 수 제한의 고정 창과 시험 시계 — D-715(간헐 실패의 원인과 대조군)."""

import itertools

import pytest

from app.core import rate_limit
from app.core.rate_limit import Limit

pytestmark = pytest.mark.anyio


@pytest.mark.real_clock
async def test_window_boundary_resets_count(committed_db, client, monkeypatch) -> None:
    """대조군 — 시계를 고정하지 않고 요청 사이에 창 경계를 넘기면 세 번째도 200(새 창). 그래서 한도 시험은 시계를 고정한다"""
    monkeypatch.setitem(rate_limit.LIMITS, "search", Limit(1, 60))
    edge = (int(rate_limit.time.time()) // 60 + 1) * 60  # 다음 창의 시작
    ticks = itertools.chain([edge - 0.2, edge - 0.1], itertools.repeat(edge + 0.1))  # 첫·둘째는 이 창, 셋째부터 다음 창
    monkeypatch.setattr(rate_limit, "clock", lambda: next(ticks))
    ip = {"X-Client-IP": "198.51.100.90"}
    assert (await client.get("/api/search", params={"q": "회의"}, headers=ip)).status_code == 200
    assert (await client.get("/api/search", params={"q": "회의"}, headers={"X-Client-IP": "198.51.100.91"})).status_code == 200
    assert (await client.get("/api/search", params={"q": "회의"}, headers=ip)).status_code == 200  # 고정 창 — 넘어가면 다시 센다


async def test_fixed_clock_keeps_one_window(committed_db, client, monkeypatch) -> None:
    """고정된 시계(conftest)에서는 같은 순서가 429 — 시험 시간이 길어도 결과가 같다"""
    monkeypatch.setitem(rate_limit.LIMITS, "search", Limit(1, 60))
    ip = {"X-Client-IP": "198.51.100.92"}
    assert (await client.get("/api/search", params={"q": "회의"}, headers=ip)).status_code == 200
    assert (await client.get("/api/search", params={"q": "회의"}, headers=ip)).status_code == 429
