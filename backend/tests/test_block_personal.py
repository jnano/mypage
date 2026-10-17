"""회원 블록(GET /api/me/page-state?blocks=) — 홈블록 설계도 §5.2 '회원 블록 호출'·§5.4·§6.1·§13('page-state 쿼리 수')."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.viewer import GUEST, Viewer
from app.blocks.frame import frame_bundle, personal_blocks
from app.models import Block, BoardAccess, Layout
from tests.factories import make_board, make_member, make_post
from tests.helpers import as_member, count_queries

pytestmark = pytest.mark.anyio


async def _layout(db: AsyncSession) -> int:
    row = Layout(name="기본", is_default=True)
    db.add(row)
    await db.flush()
    return row.id


async def _block(db: AsyncSession, lid: int, type_: str, config: dict, *, region: str | None = "top", parent: int | None = None, **kw) -> int:
    row = Block(layout_id=lid, region=None if parent else region, parent_id=parent, type=type_, config=config, **kw)
    db.add(row)
    await db.flush()
    return row.id


def viewer(member, level: int | None = None) -> Viewer:
    return Viewer(member_id=member.id, level=member.level if level is None else level)


async def test_block_view_rules(db: AsyncSession) -> None:
    user = await make_member(db, level=1)
    lid = await _layout(db)
    member = await _block(db, lid, "heading", {"text": "회원 공지"}, audience="member")
    leveled = await _block(db, lid, "heading", {"text": "등급 3"}, min_level=3)
    guest = await _block(db, lid, "heading", {"text": "가입 안내"}, audience="guest")
    hidden = await _block(db, lid, "heading", {"text": "숨김"}, audience="member", is_active=False)
    group = await _block(db, lid, "group", {"title": "회원 묶음"}, audience="member")
    await _block(db, lid, "heading", {"text": "묶음 안"}, parent=group)
    await _block(db, lid, "heading", {"text": "묶음 안 등급 5"}, parent=group, min_level=5)
    ids = [member, leveled, guest, hidden, group]
    got = await personal_blocks(db, viewer(user), ids)
    assert set(got) == {member, group}  # 등급 모자람·비회원 대상·숨김은 없다(빈 값이 아니라 없음)
    assert got[member]["data"]["text"] == "회원 공지"
    assert [c["data"]["text"] for c in got[group]["children"]] == ["묶음 안"]
    assert set(await personal_blocks(db, viewer(user, 3), ids)) == {member, leveled, group}
    assert set(await personal_blocks(db, GUEST, ids)) == {guest}  # 판정 함수만으로도 비회원에게는 비회원 대상만(API 는 비회원이면 아예 비움)


async def test_member_only_board_posts_for_listed_member(db: AsyncSession) -> None:
    author = await make_member(db, level=1)
    outsider = await make_member(db, level=1)
    insider = await make_member(db, level=1)
    board = await make_board(db, slug="members", read_level=2, list_level=2)
    db.add(BoardAccess(board_id=board.id, subject_type="member", subject_id=insider.id, can_read=True))
    await make_post(db, board, author, title="회원 글")
    lid = await _layout(db)
    bid = await _block(db, lid, "recent_posts", {"board_ids": [board.id]})
    links = await _block(db, lid, "board_links", {"board_ids": [board.id]})
    public = await frame_bundle(db)
    assert bid in public["personal_block_ids"] and "회원 글" not in str(public)
    seen = await personal_blocks(db, viewer(insider), [bid, links])
    assert [i["title"] for i in seen[bid]["data"]["items"]] == ["회원 글"]  # 명부로 읽는 회원
    assert seen[links]["data"]["items"][0]["href"] == "/boards/members"
    not_seen = await personal_blocks(db, viewer(outsider), [bid, links])
    assert not_seen[bid]["data"]["items"] == []  # 블록은 보이지만 못 읽는 글은 없다(§6.1 글 판정 절)
    assert links not in not_seen  # 목록을 못 보는 게시판뿐이면 바로가기 블록이 비어 그리지 않는다


async def test_menu_items_by_level(db: AsyncSession) -> None:
    user = await make_member(db, level=2)
    menu = (await db.execute(text("INSERT INTO menus (name) VALUES ('주 메뉴') RETURNING id"))).scalar_one()
    await db.execute(
        text("INSERT INTO menu_items (menu_id, sort_order, label, link_kind, url, min_level) VALUES (:m, 0, '공지', 'url', '/n', 0), (:m, 1, '등급 2', 'url', '/l', 2), (:m, 2, '등급 5', 'url', '/x', 5)"),
        {"m": menu},
    )
    lid = await _layout(db)
    nav = await _block(db, lid, "menu", {"menu_id": menu, "label": "주 메뉴"}, region="nav")
    public = await frame_bundle(db)
    assert nav in public["personal_block_ids"]
    got = await personal_blocks(db, viewer(user), [nav])
    assert [i["label"] for i in got[nav]["data"]["items"]] == ["공지", "등급 2"]


async def test_query_budget_30_blocks(db: AsyncSession) -> None:
    """회원 블록 30개(종류 섞음) — 호출 하나당 쿼리 ≤ 8(§5.4, 검토 N-7)"""
    user = await make_member(db, level=5)
    boards = [await make_board(db, slug=f"b{i}") for i in range(5)]
    for b in boards:
        await make_post(db, b, user, published_at=datetime.now(UTC))
    menu = (await db.execute(text("INSERT INTO menus (name) VALUES ('주 메뉴') RETURNING id"))).scalar_one()
    await db.execute(text("INSERT INTO menu_items (menu_id, label, link_kind, board_id) VALUES (:m, '게시판', 'board', :b)"), {"m": menu, "b": boards[0].id})
    lid = await _layout(db)
    ids = [b.id for b in boards]
    blocks = []
    for i in range(6):
        blocks.append(await _block(db, lid, "recent_posts", {"board_ids": ids}, audience="member", sort_order=i))
        blocks.append(await _block(db, lid, "recent_comments", {"board_ids": ids}, audience="member", sort_order=i))
        blocks.append(await _block(db, lid, "board_links", {"board_ids": ids}, audience="member", sort_order=i))
        blocks.append(await _block(db, lid, "menu", {"menu_id": menu, "label": f"메뉴 {i}"}, audience="member", sort_order=i))
        blocks.append(await _block(db, lid, "text", {"source": "**회원** 안내"}, min_level=1, sort_order=i))
    with count_queries() as q:
        got = await personal_blocks(db, viewer(user), blocks)
    assert len(blocks) == 30 and len(got) == 30
    assert q["n"] <= 8, q["sql"]


async def test_http(dev_header, committed_db, client) -> None:
    user = await make_member(committed_db, level=1)
    lid = await _layout(committed_db)
    bid = await _block(committed_db, lid, "heading", {"text": "회원 공지"}, audience="member")
    await committed_db.commit()
    res = await client.get("/api/me/page-state", params={"blocks": str(bid)}, headers=as_member(user.id))
    assert res.status_code == 200 and res.json()["blocks"][str(bid)]["data"]["text"] == "회원 공지"
    assert res.headers["cache-control"] == "no-store"
    assert res.json()["viewer"] is True
    assert (await client.get("/api/me/page-state", params={"blocks": str(bid)})).json() == {"viewer": False, "blocks": {}}  # 비회원
    many = ",".join(str(i) for i in range(1, 32))
    assert (await client.get("/api/me/page-state", params={"blocks": many}, headers=as_member(user.id))).status_code == 422


@pytest.mark.parametrize(
    ("active", "audience", "min_level", "member", "level", "expected"),
    [
        (True, "all", 0, False, 0, True),
        (False, "all", 0, True, 9, False),  # 숨김은 누구에게도
        (True, "member", 0, False, 0, False),
        (True, "member", 0, True, 1, True),
        (True, "guest", 0, False, 0, True),
        (True, "guest", 0, True, 1, False),  # 가입 안내는 회원에게 안 보인다
        (True, "all", 3, True, 2, False),
        (True, "all", 3, True, 3, True),
    ],
)
def test_block_view_table(active, audience, min_level, member, level, expected) -> None:
    """block.view(§6.1) — 공개 묶음의 개인 블록 판정과 회원 블록 판정이 이 함수 하나를 쓴다(permissions.block_view)"""
    from types import SimpleNamespace

    from app.permissions import block_view

    row = SimpleNamespace(is_active=active, audience=audience, min_level=min_level)
    viewer = Viewer(member_id=7 if member else None, level=level)
    assert block_view(viewer, row) is expected


async def test_children_of_hidden_or_leveled_group_by_id(db: AsyncSession) -> None:
    """묶음 안 자식을 id 로 바로 물어도 부모 묶음의 보이기를 본다(코드 검토 v9 B-1 재현 그대로)"""
    user = await make_member(db, level=1)
    lid = await _layout(db)
    vip = await _block(db, lid, "group", {"title": "VIP"}, min_level=5)
    code = await _block(db, lid, "heading", {"text": "VIP 할인 코드 1234"}, parent=vip)
    draft = await _block(db, lid, "group", {"title": "초안"}, is_active=False)
    secret = await _block(db, lid, "heading", {"text": "초안 내용"}, parent=draft)
    members = await _block(db, lid, "group", {"title": "회원"}, audience="member")
    inside = await _block(db, lid, "heading", {"text": "회원 묶음 안"}, parent=members)
    got = await personal_blocks(db, viewer(user), [code, secret, inside])
    assert set(got) == {inside}  # 등급·숨김 묶음의 자식은 없고, 볼 수 있는 묶음의 자식만
    assert set(await personal_blocks(db, viewer(user, 5), [code, secret])) == {code}


async def test_http_board_and_blocks_together_rejected(dev_header, committed_db, client) -> None:
    user = await make_member(committed_db, level=1)
    await committed_db.commit()
    res = await client.get("/api/me/page-state", params={"board": "free", "blocks": "1"}, headers=as_member(user.id))
    assert res.status_code == 422
