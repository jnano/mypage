"""메뉴 관리 API — 홈블록 설계도 §4.5·§4.6·§7·§11·§13('동시 저장'·'트리 저장'·'파급')."""

import asyncio

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.blocks.limits import MAX_MENU_DEPTH, MAX_MENU_ITEMS
from app.models import BoardModerator, ModerationLog
from tests.factories import make_board, make_member
from tests.helpers import as_member

pytestmark = pytest.mark.anyio


async def _setup(db: AsyncSession):
    admin = await make_member(db, level=9, is_admin=True)
    user = await make_member(db, level=1)
    board = await make_board(db, slug="free")
    page_id = (await db.execute(text("INSERT INTO pages (path, title) VALUES ('/about', '소개') RETURNING id"))).scalar_one()
    await db.commit()
    return admin.id, user.id, board.id, page_id


async def _create(client, admin: int, name: str = "주 메뉴") -> dict:
    res = await client.post("/api/admin/menus", json={"name": name}, headers=as_member(admin))
    assert res.status_code == 201, res.text
    assert res.headers["etag"] == '"1"'
    return res.json()


async def _put(client, admin: int, menu_id: int, version: int | None, body: dict):
    headers = as_member(admin) | ({"If-Match": f'"{version}"'} if version is not None else {})
    return await client.put(f"/api/admin/menus/{menu_id}", json=body, headers=headers)


def url(u: str) -> dict:
    return {"kind": "url", "url": u}


async def test_only_admins(dev_header, committed_db, client) -> None:
    """운영자만(U-3) — 게시판 담당자도 안 된다"""
    admin, user, board_id, _ = await _setup(committed_db)
    mod = await make_member(committed_db, level=2)
    committed_db.add(BoardModerator(board_id=board_id, member_id=mod.id))
    await committed_db.commit()
    assert (await client.get("/api/admin/menus", headers=as_member(mod.id))).json()["code"] == "admin_only"
    assert (await client.get("/api/admin/menus", headers=as_member(user))).json()["code"] == "staff_only"
    assert (await client.post("/api/admin/menus", json={"name": "x"}, headers=as_member(user))).status_code == 403
    assert (await client.get("/api/admin/menus")).status_code in (401, 403)


async def test_create_list_and_name_conflict(dev_header, committed_db, client) -> None:
    admin, *_ = await _setup(committed_db)
    menu = await _create(client, admin)
    assert menu["items"] == [] and menu["invalidate"] == {"now": [f"menu:{menu['id']}"], "max": []}
    res = await client.post("/api/admin/menus", json={"name": "  주 메뉴 "}, headers=as_member(admin))
    assert (res.status_code, res.json()["code"]) == (409, "menu_name_taken")
    assert (await client.post("/api/admin/menus", json={"name": "   "}, headers=as_member(admin))).status_code == 422
    listed = (await client.get("/api/admin/menus", headers=as_member(admin))).json()["menus"]
    assert [(m["name"], m["items"]) for m in listed] == [("주 메뉴", 0)]


async def test_save_tree_keeps_ids_and_moves_children(dev_header, committed_db, client) -> None:
    admin, _, board_id, page_id = await _setup(committed_db)
    menu = await _create(client, admin)
    body = {
        "name": "주 메뉴",
        "items": [
            {"label": "소개", "children": [{"label": "인사말", "link": {"kind": "page", "page_id": page_id}},
                                          {"label": "연혁", "link": url("/about/history"), "children": [{"label": "3단", "link": url("/a/b/c")}]}]},
            {"label": "자유게시판", "link": {"kind": "board", "board_id": board_id, "new_window": True}, "min_level": 2, "is_active": False},
        ],
    }  # fmt: skip
    res = await _put(client, admin, menu["id"], 1, body)
    assert res.status_code == 200, res.text
    assert res.headers["etag"] == '"2"'
    saved = res.json()
    intro, board_item = saved["items"]
    history = intro["children"][1]
    assert board_item["link"] == {"kind": "board", "board_id": board_id, "new_window": True}
    assert (board_item["min_level"], board_item["is_active"]) == (2, False)
    assert intro["link"] is None and history["children"][0]["label"] == "3단"

    # '소개' 를 지우고 그 아래 '연혁'(자식 포함)을 맨 위로 옮긴다 — 옮겨 간 항목·그 자식은 함께 지워지지 않고 id 가 그대로
    moved = {"id": history["id"], "label": "연혁", "link": url("/about/history"),
             "children": [{"id": history["children"][0]["id"], "label": "3단", "link": url("/a/b/c")}]}  # fmt: skip
    res = await _put(client, admin, menu["id"], 2, {"name": "주 메뉴", "items": [moved, {"id": board_item["id"], "label": "게시판", "link": url("/boards/free")}]})
    assert res.status_code == 200, res.text
    items = res.json()["items"]
    assert [(i["id"], i["label"]) for i in items] == [(history["id"], "연혁"), (board_item["id"], "게시판")]
    assert items[0]["children"][0]["id"] == history["children"][0]["id"]
    assert items[1]["link"] == {"kind": "url", "url": "/boards/free", "new_window": False}
    count = (await committed_db.execute(text("SELECT count(*) FROM menu_items WHERE menu_id = :m"), {"m": menu["id"]})).scalar_one()
    assert count == 3  # 소개·인사말이 지워졌다

    log = (await committed_db.execute(select(ModerationLog).where(ModerationLog.action == "menu.update").order_by(ModerationLog.id.desc()))).scalars().first()
    assert log.target_type == "menu" and set(log.after["removed"]) == {intro["id"], intro["children"][0]["id"]}
    assert set(log.after["updated"]) >= {history["id"], board_item["id"]}


async def test_version_rules(dev_header, committed_db, client) -> None:
    admin, *_ = await _setup(committed_db)
    menu = await _create(client, admin)
    body = {"name": "주 메뉴", "items": [{"label": "공지", "link": url("/boards/notice")}]}
    assert (await _put(client, admin, menu["id"], None, body)).status_code == 428
    res = await _put(client, admin, menu["id"], 7, body)
    assert (res.status_code, res.json()["code"], res.headers["etag"]) == (412, "version_conflict", '"1"')
    assert (await _put(client, admin, menu["id"], 1, body)).status_code == 200
    assert (await _put(client, admin, 999999, 1, body)).status_code == 404


async def test_concurrent_saves_one_wins(dev_header, committed_db, client) -> None:
    """같은 버전으로 동시에 두 번 — 메뉴 행 잠금 + 버전 비교로 하나만 성공(반복, D-708)"""
    admin, *_ = await _setup(committed_db)
    menu = await _create(client, admin)
    for round_ in range(5):
        version = 1 + round_
        a = _put(client, admin, menu["id"], version, {"name": "주 메뉴", "items": [{"label": "가", "link": url("/a")}]})
        b = _put(client, admin, menu["id"], version, {"name": "주 메뉴", "items": [{"label": "나", "link": url("/b")}]})
        codes = sorted(r.status_code for r in await asyncio.gather(a, b))
        assert codes == [200, 412], (round_, codes)


@pytest.mark.parametrize(
    ("items", "code"),
    [
        # 단계 초과
        ([{"label": "1", "children": [{"label": "2", "children": [{"label": "3", "children": [{"label": "4", "link": url("/x")}]}]}]}], "validation_error"),
        ([{"label": "  ", "link": url("/x")}], "validation_error"),  # 빈 이름
        ([{"label": "나쁜 링크", "link": url("javascript:alert(1)")}], "validation_error"),
        ([{"label": "없는 페이지", "link": {"kind": "page", "page_id": 999999}}], "dangling_ref"),
        ([{"label": "없는 게시판", "link": {"kind": "board", "board_id": 999999}}], "dangling_ref"),
        ([{"label": "모르는 칸", "link": url("/x"), "color": "red"}], "validation_error"),
    ],
)
async def test_rejected_trees(dev_header, committed_db, client, items, code) -> None:
    admin, *_ = await _setup(committed_db)
    menu = await _create(client, admin)
    res = await _put(client, admin, menu["id"], 1, {"name": "주 메뉴", "items": items})
    assert (res.status_code, res.json()["code"]) == (422, code)
    # 실패한 저장은 아무것도 바꾸지 않는다
    assert (await client.get(f"/api/admin/menus/{menu['id']}", headers=as_member(admin))).json()["version"] == 1


async def test_depth_limit_is_the_constant(dev_header, committed_db, client) -> None:
    admin, *_ = await _setup(committed_db)
    menu = await _create(client, admin)
    item: dict = {"label": f"{MAX_MENU_DEPTH}단", "link": url("/x")}
    for depth in range(MAX_MENU_DEPTH - 1, 0, -1):
        item = {"label": f"{depth}단", "children": [item]}
    assert (await _put(client, admin, menu["id"], 1, {"name": "주 메뉴", "items": [item]})).status_code == 200
    too_many = [{"label": f"{i}", "link": url("/x")} for i in range(MAX_MENU_ITEMS + 1)]
    assert (await _put(client, admin, menu["id"], 2, {"name": "주 메뉴", "items": too_many})).status_code == 422


async def test_other_menus_items_and_duplicates_rejected(dev_header, committed_db, client) -> None:
    admin, *_ = await _setup(committed_db)
    a = await _create(client, admin, "가 메뉴")
    b = await _create(client, admin, "나 메뉴")
    saved = (await _put(client, admin, a["id"], 1, {"name": "가 메뉴", "items": [{"label": "공지", "link": url("/n")}]})).json()
    theirs = saved["items"][0]["id"]
    res = await _put(client, admin, b["id"], 1, {"name": "나 메뉴", "items": [{"id": theirs, "label": "가로채기", "link": url("/n")}]})
    assert (res.status_code, res.json()["code"]) == (422, "item_not_in_menu")
    res = await _put(client, admin, a["id"], 2, {"name": "가 메뉴", "items": [{"id": theirs, "label": "1", "link": url("/n")}, {"id": theirs, "label": "2", "link": url("/n")}]})
    assert res.status_code == 422
    # 다른 메뉴 이름으로 바꾸면 409(UNIQUE 가 최종 판정)
    res = await _put(client, admin, a["id"], 2, {"name": "나 메뉴", "items": []})
    assert (res.status_code, res.json()["code"]) == (409, "menu_name_taken")


async def test_delete_menu_and_board_in_menu(dev_header, committed_db, client) -> None:
    admin, _, board_id, page_id = await _setup(committed_db)
    menu = await _create(client, admin)
    items = [{"label": "자유게시판", "link": {"kind": "board", "board_id": board_id}}, {"label": "소개", "link": {"kind": "page", "page_id": page_id}}]
    saved = (await _put(client, admin, menu["id"], 1, {"name": "주 메뉴", "items": items})).json()
    # 메뉴가 가리키는 게시판은 지울 수 없다 — 500 이 아니라 409 + 어느 항목인지(§4.5·§11)
    res = await client.delete("/api/boards/free", headers=as_member(admin))
    assert (res.status_code, res.json()["code"]) == (409, "in_menu")
    assert res.json()["errors"] == [{"field": f"menu_items.{saved['items'][0]['id']}", "message": "이 메뉴 항목이 가리킵니다"}]
    # 메뉴를 지우면 항목이 함께 사라지고, 그 뒤에는 지울 수 있다
    res = await client.delete(f"/api/admin/menus/{menu['id']}", headers=as_member(admin))
    assert res.status_code == 200 and res.json()["invalidate"] == {"now": [f"menu:{menu['id']}"], "max": []}
    assert (await committed_db.execute(text("SELECT count(*) FROM menu_items"))).scalar_one() == 0
    assert (await client.delete("/api/boards/free", headers=as_member(admin))).status_code == 200
    assert (await client.delete(f"/api/admin/menus/{menu['id']}", headers=as_member(admin))).status_code == 404
    actions = set((await committed_db.execute(select(ModerationLog.action).where(ModerationLog.target_type == "menu"))).scalars())
    assert actions == {"menu.create", "menu.update", "menu.delete"}


async def test_target_deleted_between_check_and_insert(dev_header, committed_db, client, monkeypatch) -> None:
    """확인과 넣기 사이에 대상이 사라진 틈 — FK 가 막은 것을 500 이 아니라 422 로(코드 검토 v6 N-3)"""
    from app.blocks import menus

    async def skip(*_: object) -> None:  # 확인을 건너뛰어 틈을 흉내 낸다
        return None

    admin, *_ = await _setup(committed_db)
    menu = await _create(client, admin)
    monkeypatch.setattr(menus, "_check_refs", skip)
    res = await _put(client, admin, menu["id"], 1, {"name": "주 메뉴", "items": [{"label": "사라진 페이지", "link": {"kind": "page", "page_id": 999999}}]})
    assert (res.status_code, res.json()["code"]) == (422, "dangling_ref")
    assert (await client.get(f"/api/admin/menus/{menu['id']}", headers=as_member(admin))).json()["version"] == 1
