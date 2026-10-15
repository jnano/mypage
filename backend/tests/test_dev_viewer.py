"""개발용 Viewer 헤더 가드(§11)와 Viewer 로드(§5.1)."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.viewer import GUEST, Viewer, get_viewer
from app.core import problems
from app.core.config import Settings, settings
from app.models import MemberGroup, MemberGroupMember, MemberSanction
from tests.factories import make_board, make_member

pytestmark = pytest.mark.anyio

SECRET = "s" * 24

# ── 설정 가드: 방어선 ① ENV=dev 전용 ② 공유 비밀 ──────────────


def test_prod_with_dev_header_fails_to_start() -> None:
    with pytest.raises(ValidationError, match="ENV=dev"):
        Settings(env="prod", dev_viewer_header=True, dev_viewer_secret=SECRET)


def test_test_env_with_dev_header_fails_to_start() -> None:
    with pytest.raises(ValidationError, match="ENV=dev"):
        Settings(env="test", dev_viewer_header=True, dev_viewer_secret=SECRET)


def test_dev_header_requires_secret() -> None:
    with pytest.raises(ValidationError, match="DEV_VIEWER_SECRET"):
        Settings(env="dev", dev_viewer_header=True, dev_viewer_secret="short")


def test_dev_with_header_and_secret_is_allowed() -> None:
    assert Settings(env="dev", dev_viewer_header=True, dev_viewer_secret=SECRET).dev_viewer_header


def test_default_env_is_prod() -> None:
    assert Settings.model_fields["env"].default == "prod"


# ── 요청 처리 ──────────────────────────────────────────────

probe = FastAPI()
problems.install(probe)


@probe.get("/whoami")
async def whoami(viewer: Viewer = Depends(get_viewer)) -> dict:
    return {
        "member_id": viewer.member_id,
        "level": viewer.level,
        "is_admin": viewer.is_admin,
        "group_ids": sorted(viewer.group_ids),
        "sanctions": sorted(viewer.sanctions),
    }


@pytest.fixture
def dev_header_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "dev_viewer_header", True)
    monkeypatch.setattr(settings, "dev_viewer_secret", SECRET)


async def _whoami(header: str | None) -> tuple[int, dict]:
    headers = {"X-Dev-Member": header} if header is not None else {}
    async with AsyncClient(transport=ASGITransport(app=probe), base_url="http://test") as c:
        res = await c.get("/whoami", headers=headers)
    return res.status_code, res.json()


async def test_header_ignored_when_disabled(committed_db: AsyncSession) -> None:
    m = await make_member(committed_db, level=9, is_admin=True)
    await committed_db.commit()
    status, body = await _whoami(f"{m.id}; key={SECRET}")
    assert status == 200 and body["member_id"] is None and body["level"] == 0


async def test_no_header_is_guest(dev_header_on: None) -> None:
    status, body = await _whoami(None)
    assert (status, body["member_id"]) == (200, None)


@pytest.mark.parametrize("header", ["12; key=wrong-secret-value-xx", "12", "abc; key=x", "12; k=x"])
async def test_bad_header_is_401_problem(dev_header_on: None, header: str) -> None:
    async with AsyncClient(transport=ASGITransport(app=probe), base_url="http://test") as c:
        res = await c.get("/whoami", headers={"X-Dev-Member": header})
    assert res.status_code == 401
    assert res.headers["content-type"] == "application/problem+json"
    assert res.json()["code"] == "dev_viewer_invalid"


async def test_valid_header_loads_viewer(dev_header_on: None, committed_db: AsyncSession) -> None:
    db = committed_db
    m = await make_member(db, level=3)
    board = await make_board(db)
    g1, g2 = MemberGroup(name="운영진"), MemberGroup(name="회의 참석자")
    db.add_all([g1, g2])
    await db.flush()
    now = datetime.now(UTC)
    db.add_all(
        [
            MemberGroupMember(group_id=g1.id, member_id=m.id),
            MemberGroupMember(group_id=g2.id, member_id=m.id),
            # 사이트 전체·유효 → 포함
            MemberSanction(member_id=m.id, actions=["comment"], reason="r"),
            # 게시판 단위 → Viewer 에는 없음(BoardRole 몫)
            MemberSanction(member_id=m.id, scope_board_id=board.id, actions=["write"], reason="r"),
            # 끝남·해제됨·아직 시작 전 → 제외
            MemberSanction(
                member_id=m.id, actions=["upload"], reason="r", ends_at=now - timedelta(days=1)
            ),
            MemberSanction(member_id=m.id, actions=["upload"], reason="r", revoked_at=now),
            MemberSanction(
                member_id=m.id, actions=["upload"], reason="r", starts_at=now + timedelta(days=1)
            ),
        ]
    )
    await db.commit()

    status, body = await _whoami(f"{m.id}; key={SECRET}")
    assert status == 200
    assert body == {
        "member_id": m.id,
        "level": 3,
        "is_admin": False,
        "group_ids": sorted([g1.id, g2.id]),
        "sanctions": ["comment"],
    }


async def test_withdrawn_or_unknown_member_is_guest(
    dev_header_on: None, committed_db: AsyncSession
) -> None:
    m = await make_member(
        committed_db, status="withdrawn", withdrawn_at=datetime.now(UTC), level=5
    )
    await committed_db.commit()
    for member_id in (m.id, 999_999):
        status, body = await _whoami(f"{member_id}; key={SECRET}")
        assert (status, body["member_id"], body["level"]) == (200, None, 0)


async def test_health_warns_when_enabled(dev_header_on: None, client: AsyncClient) -> None:
    assert (await client.get("/api/health")).json()["warning"] == "dev_viewer_header_enabled"


async def test_health_quiet_when_disabled(client: AsyncClient) -> None:
    assert "warning" not in (await client.get("/api/health")).json()


def test_guest_constant() -> None:
    assert GUEST.member_id is None and GUEST.level == 0 and not GUEST.is_member
