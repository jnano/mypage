import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.engine import make_url

# 앱 설정을 import 하기 전에 DB 를 테스트 DB 로 바꾼다(환경 변수가 .env 보다 우선한다).
# 개발 DB 를 오염시키지 않도록 이름이 _test 로 끝나지 않으면 시작하지 않는다.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://taehunkang@localhost:5432/mypage_test"
)
if not (make_url(TEST_DATABASE_URL).database or "").endswith("_test"):
    raise RuntimeError(f"테스트 DB 이름은 _test 로 끝나야 합니다: {TEST_DATABASE_URL}")
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.db.session import engine  # noqa: E402
from app.main import app  # noqa: E402


# asyncpg 연결은 이벤트 루프에 묶이므로 세션 전체가 루프 하나를 쓴다
@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session", autouse=True)
async def _dispose_engine(anyio_backend: str) -> AsyncIterator[None]:
    yield
    await engine.dispose()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
