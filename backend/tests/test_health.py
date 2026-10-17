import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.db.session import SessionLocal

pytestmark = pytest.mark.anyio


async def test_health(client: AsyncClient) -> None:
    res = await client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


async def test_health_db_uses_test_database(client: AsyncClient) -> None:
    res = await client.get("/api/health/db")
    assert res.status_code == 200

    async with SessionLocal() as db:
        name = (await db.execute(text("SELECT current_database()"))).scalar_one()
    assert name.endswith("_test")


def test_api_docs_off_in_prod() -> None:
    """FastAPI 기본 문서는 운영에서 끈다(설계도 §11) — 개발·시험에서는 켠다"""
    from fastapi import FastAPI

    from app.main import docs_urls

    assert docs_urls("prod") == {"docs_url": None, "redoc_url": None, "openapi_url": None}
    assert docs_urls("dev")["openapi_url"] == "/openapi.json" and docs_urls("test")["docs_url"] == "/docs"
    prod = FastAPI(**docs_urls("prod"))
    assert {getattr(r, "path", "") for r in prod.routes} & {"/docs", "/redoc", "/openapi.json"} == set()
