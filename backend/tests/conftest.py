import os
import time as _time
from collections.abc import AsyncIterator
from pathlib import Path

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
# 로컬 .env 의 개발 설정(ENV=dev, 개발 헤더)이 테스트에 섞이지 않게 고정한다
os.environ["ENV"] = "test"
os.environ["DEV_VIEWER_HEADER"] = "false"
os.environ["INTERNAL_API_SECRET"] = INTERNAL_SECRET = "test-internal-secret-0123456789abcdef"

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.core import rate_limit  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from tests.helpers import DEV_SECRET  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]


def alembic_config() -> Config:
    return Config(str(BACKEND_DIR / "alembic.ini"))


@pytest.fixture(scope="session")
def migrated_db() -> None:
    """테스트 DB 를 비우고 마이그레이션을 처음부터 적용한다 — downgrade 경로도 매번 확인된다."""
    cfg = alembic_config()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


# asyncpg 연결은 이벤트 루프에 묶이므로 세션 전체가 루프 하나를 쓴다
@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session", autouse=True)
async def _dispose_engine(anyio_backend: str, migrated_db: None) -> AsyncIterator[None]:
    yield
    await engine.dispose()


@pytest.fixture
async def db() -> AsyncIterator[AsyncSession]:
    """테스트마다 바깥 트랜잭션을 열고 끝에 되돌린다. 세션의 commit 은 SAVEPOINT 가 된다."""
    async with engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(
            bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()


@pytest.fixture
async def committed_db() -> AsyncIterator[AsyncSession]:
    """커밋이 실제로 일어나는 세션 — 다른 연결(예: Viewer 로드의 별도 세션)이 데이터를 봐야 할 때.
    끝나면 모든 표를 비운다."""
    async with SessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
            tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
            await session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
            await session.commit()


@pytest.fixture(autouse=True)
def file_roots(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """파일 저장소를 테스트마다 임시 폴더로."""
    monkeypatch.setattr(settings, "media_root", str(tmp_path / "media"))
    monkeypatch.setattr(settings, "private_root", str(tmp_path / "private"))
    return tmp_path


@pytest.fixture(autouse=True)
def rate_limit_clock(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """요청 수 제한 시계(공개 지점 rate_limit.clock)를 이 시험의 시작 시각으로 고정한다. 제한은 고정 창(60초 등)이라, 한도를
    넘기는 시험이 요청 사이에 창 경계를 지나면 새 창에서 다시 세어 429 대신 200 이 나왔다(느린 실행에서 간헐 실패 — D-715).
    카운터 동작은 그대로다. 창 경계 자체를 보는 시험은 @pytest.mark.real_clock 으로 빠진다(그 시험이 시계를 직접 정한다)"""
    if request.node.get_closest_marker("real_clock"):
        return
    now = _time.time()
    monkeypatch.setattr(rate_limit, "clock", lambda: now)


@pytest.fixture
def dev_header(monkeypatch: pytest.MonkeyPatch) -> None:
    """개발용 Viewer 헤더를 켠다 — tests.helpers.as_member(id) 로 요청한다."""
    monkeypatch.setattr(settings, "dev_viewer_header", True)
    monkeypatch.setattr(settings, "dev_viewer_secret", DEV_SECRET)


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """Next 서버처럼 내부 비밀 헤더를 싣는 클라이언트."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Internal-Secret": INTERNAL_SECRET},
    ) as c:
        yield c


@pytest.fixture
async def browser() -> AsyncIterator[AsyncClient]:
    """rewrites 로 FastAPI 에 바로 온 브라우저 요청 — 내부 비밀이 없다."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
