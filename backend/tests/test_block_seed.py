"""개발 시드의 홈블록 몫(scripts/seed_homeblock.py) — 운영자 저장 함수를 그대로 거쳐 시드가 깨지면 CI 접근성 단계 전에 여기서 안다."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.viewer import Viewer
from app.blocks.frame import frame_bundle
from scripts.seed_homeblock import SAMPLE_PATH, seed_homeblock
from tests.factories import make_board, make_member

pytestmark = pytest.mark.anyio


async def test_seed_homeblock(db: AsyncSession) -> None:
    admin = await make_member(db, level=9, is_admin=True)
    boards = {slug: (await make_board(db, slug=slug, name=slug, list_level=2 if slug == "members" else 0)).id for slug in ("notice", "free", "members")}
    out = await seed_homeblock(db, Viewer(member_id=admin.id, level=9, is_admin=True), boards)
    sample = await frame_bundle(db, path=SAMPLE_PATH)
    types = {b["type"] for b in sample["page"]["blocks"]}
    assert {"heading", "text", "buttons", "link_list", "video", "details", "divider", "group", "columns", "module"} <= types
    home = await frame_bundle(db, path="/")
    assert [b["type"] for b in home["page"]["blocks"]] == ["recent_posts", "recent_posts"]
    board = await frame_bundle(db, board_slug="free")
    assert board["layout"]["id"] == out["board_layout"] and board["layout"]["regions"]["aside"][0]["type"] == "sub_menu"  # 옆 메뉴가 있는 게시판 화면
