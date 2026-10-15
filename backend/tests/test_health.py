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
