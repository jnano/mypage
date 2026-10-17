"""쓰기 경계(§3.5, §6) — 내부 비밀 헤더가 없는 상태 변경 요청은 거부한다."""

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from starlette.requests import Request

from app.core import csrf
from app.core.config import Settings, settings

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("method", ["POST", "PATCH", "PUT", "DELETE"])
async def test_browser_write_is_rejected(browser: AsyncClient, method: str) -> None:
    res = await browser.request(method, "/api/boards/free/posts", json={})
    assert res.status_code == 403
    assert res.headers["content-type"] == "application/problem+json"
    assert res.json()["code"] == "csrf_forbidden"


async def test_wrong_secret_is_rejected(browser: AsyncClient) -> None:
    res = await browser.post("/api/editor/preview", json={"markdown": "x"}, headers={"X-Internal-Secret": "nope"})
    assert res.json()["code"] == "csrf_forbidden"


async def test_reads_need_no_secret(browser: AsyncClient) -> None:
    assert (await browser.get("/api/health")).status_code == 200


async def test_internal_write_passes_the_boundary(client: AsyncClient) -> None:
    # 경계는 통과하고, 그다음 판정(로그인 필요)에서 멈춘다
    res = await client.post("/api/reports", json={"target_type": "post", "target_id": 1, "reason_code": "spam"})
    assert res.json()["code"] == "login_required"


def test_prod_requires_long_internal_secret() -> None:
    with pytest.raises(ValidationError, match="INTERNAL_API_SECRET"):
        Settings(env="prod", internal_api_secret="short")
    assert Settings(env="prod", internal_api_secret="x" * 32, email_hmac_secret="y" * 32, ip_hash_secret="z" * 32).internal_api_secret


def test_empty_secret_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "internal_api_secret", "")
    scope = {"type": "http", "method": "POST", "headers": [(b"x-internal-secret", b"")], "path": "/"}
    assert csrf.is_internal(Request(scope)) is False
