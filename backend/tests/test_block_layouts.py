"""틀 관리 API·블록 트리 저장 — 홈블록 설계도 §4.1·§4.3·§4.6·§4.7·§10·§11·§13('트리 저장'·'동시 저장')."""

import asyncio

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.blocks.limits import MAX_BLOCKS_PER_OWNER, MAX_DYNAMIC_BLOCKS
from app.models import Attachment, ModerationLog
from tests.factories import make_board, make_member
from tests.helpers import as_member

pytestmark = pytest.mark.anyio

H = {"type": "heading", "config": {"text": "안내"}}


async def _setup(db: AsyncSession):
    admin = await make_member(db, level=9, is_admin=True)
    other = await make_member(db, level=9, is_admin=True)
    board = await make_board(db, slug="free")
    menu_id = (await db.execute(text("INSERT INTO menus (name) VALUES ('주 메뉴') RETURNING id"))).scalar_one()
    await db.commit()
    return admin.id, other.id, board.id, menu_id


async def _create(client, admin: int, name: str = "기본") -> dict:
    res = await client.post("/api/admin/layouts", json={"name": name}, headers=as_member(admin))
    assert res.status_code == 201, res.text
    return res.json()


async def _put(client, admin: int, layout_id: int, version: int | None, regions: dict, name: str = "기본"):
    headers = as_member(admin) | ({"If-Match": f'"{version}"'} if version is not None else {})
    return await client.put(f"/api/admin/layouts/{layout_id}", json={"name": name, "regions": regions}, headers=headers)


async def _image(db: AsyncSession, uploader: int, key: str, *, is_image: bool = True) -> int:
    row = Attachment(uploader_id=uploader, original_name="그림.png", storage_key=key, sha256="0" * 64,
                     detected_mime="image/png", size_bytes=10, is_image=is_image)  # fmt: skip
    db.add(row)
    await db.commit()
    return row.id


async def test_only_admins(dev_header, committed_db, client) -> None:
    await _setup(committed_db)
    user = await make_member(committed_db, level=1)
    await committed_db.commit()
    assert (await client.get("/api/admin/layouts", headers=as_member(user.id))).status_code == 403
    assert (await client.post("/api/admin/layouts", json={"name": "x"}, headers=as_member(user.id))).status_code == 403


async def test_save_tree_keeps_ids_moves_and_removes(dev_header, committed_db, client) -> None:
    admin, _, board_id, menu_id = await _setup(committed_db)
    layout = await _create(client, admin)
    assert layout["regions"] == {r: [] for r in ("header", "nav", "top", "aside", "bottom", "footer")}
    regions = {
        "header": [{"type": "site_brand", "config": {}}, {"type": "account", "config": {}}],
        "nav": [{"type": "menu", "config": {"menu_id": menu_id, "label": "주 메뉴"}}],
        "aside": [{"type": "group", "config": {"title": "바로가기", "landmark": True}, "children": [
            {"type": "board_links", "config": {"board_ids": [board_id]}},
            {"type": "link_list", "config": {"items": [{"label": "자유게시판", "link": {"kind": "board", "board_id": board_id}}]}},
        ]}],
        "footer": [{"type": "footer_info", "config": {"copyright": "© 예시"}}],
    }  # fmt: skip
    res = await _put(client, admin, layout["id"], 1, regions)
    assert res.status_code == 200, res.text
    assert res.headers["etag"] == '"2"' and res.json()["invalidate"] == {"now": [f"layout:{layout['id']}"], "max": []}
    saved = res.json()["regions"]
    group = saved["aside"][0]
    assert [c["type"] for c in group["children"]] == ["board_links", "link_list"]
    assert saved["header"][0]["config"] == {"logo_attachment_id": None, "logo_alt": "", "show_name": True}  # 기본값까지 정규화

    # 묶음을 지우고 그 자식 '게시판 바로가기'를 아래 영역으로 옮긴다 — id 그대로, 함께 지워지지 않음
    moved = {"id": group["children"][0]["id"], "type": "board_links", "config": {"board_ids": [board_id]}}
    regions2 = {"header": [{"id": saved["header"][1]["id"], **regions["header"][1]}], "bottom": [moved]}
    res = await _put(client, admin, layout["id"], 2, regions2)
    assert res.status_code == 200, res.text
    out = res.json()["regions"]
    assert out["bottom"][0]["id"] == moved["id"] and out["aside"] == [] and len(out["header"]) == 1
    count = (await committed_db.execute(text("SELECT count(*) FROM blocks WHERE layout_id = :l"), {"l": layout["id"]})).scalar_one()
    assert count == 2
    log = (await committed_db.execute(select(ModerationLog).where(ModerationLog.action == "layout.update").order_by(ModerationLog.id.desc()))).scalars().first()
    assert log.target_type == "layout" and moved["id"] in log.after["updated"] and group["id"] in log.after["removed"]


@pytest.mark.parametrize(
    ("regions", "field", "code"),
    [
        ({"main": [H]}, "regions.main", "validation_error"),  # 없는 영역
        ({"top": [{"type": "outlet", "config": {}}]}, "regions.top[0].type", "validation_error"),  # 렌더러가 놓는다
        ({"top": [{"type": "banner", "config": {"attachment_id": 1, "title": "x"}}]}, "regions.top[0].type", "validation_error"),  # 페이지에만
        ({"top": [{"type": "module", "config": {"module": "board", "params": {"board_id": 1}}}]}, "regions.top[0].type", "validation_error"),
        ({"top": [{"type": "buttons", "config": {"items": [{"label": "x", "link": {"kind": "url", "url": "javascript:x"}}]}}]},
         "regions.top[0].config.items[0].link.url.url", "validation_error"),  # 오류 칸 경로
        ({"top": [{**H, "children": [H]}]}, "regions.top[0].children", "validation_error"),  # 묶음이 아닌 블록의 자식
        ({"top": [{"type": "group", "config": {}, "children": [{"type": "group", "config": {}}]}]}, "regions.top[0].children[0].type", "validation_error"),
        ({"top": [{**H, "column_index": 0}]}, "regions.top[0].column_index", "validation_error"),
        ({"top": [{"type": "group", "config": {}, "children": [{**H, "column_index": 1}]}]}, "regions.top[0].children[0].column_index", "validation_error"),
        ({"top": [{"type": "unknown", "config": {}}]}, "regions.top[0].type", "validation_error"),
    ],
)
async def test_rejected_trees(dev_header, committed_db, client, regions, field, code) -> None:
    admin, *_ = await _setup(committed_db)
    layout = await _create(client, admin)
    res = await _put(client, admin, layout["id"], 1, regions)
    assert (res.status_code, res.json()["code"]) == (422, code), res.text
    assert field in [e["field"] for e in res.json()["errors"]], res.json()["errors"]
    assert (await client.get(f"/api/admin/layouts/{layout['id']}", headers=as_member(admin))).json()["version"] == 1


async def test_columns_index_within_count(dev_header, committed_db, client) -> None:
    """칸 나누기는 페이지 전용이라 틀에서는 쓸 수 없다 — 칸 번호 규칙은 걸음 6 의 페이지 본문에서도 같은 함수"""
    from app.blocks.tree import BlockIn, TreeErrors, validate_tree

    ok = BlockIn(type="columns", config={"count": 2}, children=[BlockIn(**H, column_index=1)])
    validate_tree("page", [(None, [ok])], "blocks")
    bad = BlockIn(type="columns", config={"count": 2}, children=[BlockIn(**H, column_index=2)])
    with pytest.raises(TreeErrors) as e:
        validate_tree("page", [(None, [bad])], "blocks")
    assert e.value.errors[0]["field"] == "blocks[0].children[0].column_index"
    with pytest.raises(TreeErrors):  # 칸 나누기의 자식은 칸 번호가 있어야 한다
        validate_tree("page", [(None, [BlockIn(type="columns", config={"count": 2}, children=[BlockIn(**H)])])], "blocks")


async def test_nav_labels_must_differ(dev_header, committed_db, client) -> None:
    admin, _, _, menu_id = await _setup(committed_db)
    layout = await _create(client, admin)
    regions = {
        "nav": [{"type": "menu", "config": {"menu_id": menu_id, "label": "메뉴"}}],
        "aside": [{"type": "sub_menu", "config": {"menu_id": menu_id, "label": "메뉴"}}],
    }
    res = await _put(client, admin, layout["id"], 1, regions)
    assert res.status_code == 422 and res.json()["errors"][0]["field"] == "regions.aside[0].config"
    regions["aside"][0]["config"]["label"] = "옆 메뉴"
    assert (await _put(client, admin, layout["id"], 1, regions)).status_code == 200


async def test_limits(dev_header, committed_db, client) -> None:
    admin, _, board_id, _ = await _setup(committed_db)
    layout = await _create(client, admin)
    assert (await _put(client, admin, layout["id"], 1, {"top": [H] * (MAX_BLOCKS_PER_OWNER + 1)})).status_code == 422
    dyn = {"type": "board_links", "config": {"board_ids": [board_id]}}
    assert (await _put(client, admin, layout["id"], 1, {"top": [dyn] * (MAX_DYNAMIC_BLOCKS + 1)})).status_code == 422
    assert (await _put(client, admin, layout["id"], 1, {"top": [dyn] * MAX_DYNAMIC_BLOCKS + [H] * (MAX_BLOCKS_PER_OWNER - MAX_DYNAMIC_BLOCKS)})).status_code == 200


async def test_dangling_and_foreign(dev_header, committed_db, client) -> None:
    admin, _, _, _ = await _setup(committed_db)
    a = await _create(client, admin, "가")
    b = await _create(client, admin, "나")
    for regions in (
        {"nav": [{"type": "menu", "config": {"menu_id": 999999, "label": "주 메뉴"}}]},
        {"top": [{"type": "recent_posts", "config": {"board_ids": [999999]}}]},
        {"top": [{"type": "buttons", "config": {"items": [{"label": "x", "link": {"kind": "page", "page_id": 999999}}]}}]},
    ):
        res = await _put(client, admin, a["id"], 1, regions, "가")
        assert (res.status_code, res.json()["code"]) == (422, "dangling_ref"), res.text
    saved = (await _put(client, admin, a["id"], 1, {"top": [H]}, "가")).json()
    res = await _put(client, admin, b["id"], 1, {"top": [{"id": saved["regions"]["top"][0]["id"], **H}]}, "나")
    assert (res.status_code, res.json()["code"]) == (422, "block_not_in_owner")
    res = await _put(client, admin, a["id"], 2, {"top": [{"id": saved["regions"]["top"][0]["id"], **H}] * 2}, "가")
    assert res.status_code == 422  # 같은 블록 두 번


async def test_block_images_attach_move_and_release(dev_header, committed_db, client) -> None:
    admin, other, _, _ = await _setup(committed_db)
    layout = await _create(client, admin)
    mine = await _image(committed_db, admin, "k-mine")
    theirs = await _image(committed_db, other, "k-theirs")
    doc = await _image(committed_db, admin, "k-doc", is_image=False)
    img = lambda a: {"type": "image", "config": {"attachment_id": a, "alt": "회의실"}}  # noqa: E731

    for bad in (theirs, doc):  # 남의 임시 파일·그림이 아닌 파일
        res = await _put(client, admin, layout["id"], 1, {"top": [img(bad)]})
        assert (res.status_code, res.json()["code"]) == (422, "attachment_unavailable"), res.text
    saved = (await _put(client, admin, layout["id"], 1, {"top": [img(mine)]})).json()["regions"]["top"]
    owner = lambda a: committed_db.execute(select(Attachment.block_id).where(Attachment.id == a))  # noqa: E731
    committed_db.expire_all()
    assert (await owner(mine)).scalar_one() == saved[0]["id"]
    # 같은 저장에서 그림을 다른 블록(로고)으로 옮긴다
    regions = {"header": [{"type": "site_brand", "config": {"logo_attachment_id": mine, "logo_alt": "예시 로고"}}], "top": [{"id": saved[0]["id"], **H}]}
    res = await _put(client, admin, layout["id"], 2, regions)
    assert res.status_code == 200, res.text
    committed_db.expire_all()
    assert (await owner(mine)).scalar_one() == res.json()["regions"]["header"][0]["id"]
    # 로고 블록을 지우면 그림은 임시가 된다(24시간 뒤 정리)
    assert (await _put(client, admin, layout["id"], 3, {"top": [{"id": saved[0]["id"], **H}]})).status_code == 200
    committed_db.expire_all()
    assert (await owner(mine)).scalar_one() is None


async def test_versions_and_concurrent_saves(dev_header, committed_db, client) -> None:
    admin, *_ = await _setup(committed_db)
    layout = await _create(client, admin)
    assert (await _put(client, admin, layout["id"], None, {})).status_code == 428
    res = await _put(client, admin, layout["id"], 9, {})
    assert (res.status_code, res.headers["etag"]) == (412, '"1"')
    for round_ in range(5):
        version = 1 + round_
        codes = sorted(r.status_code for r in await asyncio.gather(
            _put(client, admin, layout["id"], version, {"top": [H]}),
            _put(client, admin, layout["id"], version, {"bottom": [H]}),
        ))  # fmt: skip
        assert codes == [200, 412], (round_, codes)


async def test_default_layout_rules(dev_header, committed_db, client) -> None:
    admin, _, board_id, _ = await _setup(committed_db)
    a = await _create(client, admin, "가")
    b = await _create(client, admin, "나")
    c = await _create(client, admin, "다")
    res = await client.post(f"/api/admin/layouts/{a['id']}/default", headers=as_member(admin))
    assert res.json()["invalidate"] == {"now": ["layouts:bindings"], "max": []}
    res = await client.delete(f"/api/admin/layouts/{a['id']}", headers=as_member(admin))
    assert (res.status_code, res.json()["code"]) == (409, "default_layout")
    # 동시에 서로 다른 틀을 기본으로 — 500·교착 없이 끝나고 기본 틀은 늘 하나(부분 UNIQUE, id 순 잠금)
    for _ in range(5):
        codes = [r.status_code for r in await asyncio.gather(
            client.post(f"/api/admin/layouts/{b['id']}/default", headers=as_member(admin)),
            client.post(f"/api/admin/layouts/{c['id']}/default", headers=as_member(admin)),
        )]  # fmt: skip
        assert set(codes) <= {200, 409}, codes
        assert (await committed_db.execute(text("SELECT count(*) FROM layouts WHERE is_default"))).scalar_one() == 1
    # 기본이 아닌 틀을 지우면 그 틀을 쓰던 게시판·대응은 기본 쪽으로(SET NULL·CASCADE)
    default_id = (await committed_db.execute(text("SELECT id FROM layouts WHERE is_default"))).scalar_one()
    victim = a["id"] if default_id != a["id"] else b["id"]
    await committed_db.execute(text("UPDATE boards SET layout_id = :l WHERE id = :b"), {"l": victim, "b": board_id})
    await committed_db.commit()
    res = await client.put("/api/admin/layout-bindings", json={"bindings": {"board": victim, "search": None}}, headers=as_member(admin))
    assert res.json()["bindings"] == {"board": victim, "search": None, "member": None, "auth": None}
    assert (await client.delete(f"/api/admin/layouts/{victim}", headers=as_member(admin))).status_code == 200
    assert (await committed_db.execute(text("SELECT layout_id FROM boards WHERE id = :b"), {"b": board_id})).scalar_one() is None
    assert (await client.get("/api/admin/layouts", headers=as_member(admin))).json()["bindings"]["board"] is None


async def test_bindings_validation(dev_header, committed_db, client) -> None:
    admin, *_ = await _setup(committed_db)
    res = await client.put("/api/admin/layout-bindings", json={"bindings": {"page": 1}}, headers=as_member(admin))
    assert res.status_code == 422  # 화면 종류가 아니다
    res = await client.put("/api/admin/layout-bindings", json={"bindings": {"board": 999999}}, headers=as_member(admin))
    assert (res.status_code, res.json()["code"]) == (422, "dangling_ref")


async def test_move_another_admins_image_between_blocks(dev_header, committed_db, client) -> None:
    """다른 운영자가 올려 이 틀에 붙어 있던 그림도 블록 사이로 옮길 수 있다 — 같은 그림을 두 블록에 두지는 못한다(v7 N-1·N-2)"""
    admin, other, _, _ = await _setup(committed_db)
    layout = await _create(client, admin)
    pic = await _image(committed_db, other, "k-other")
    image = {"type": "image", "config": {"attachment_id": pic, "alt": "회의실"}}
    res = await _put(client, other, layout["id"], 1, {"top": [image]})  # 올린 운영자가 붙인다
    assert res.status_code == 200, res.text
    block = res.json()["regions"]["top"][0]["id"]
    logo = {"type": "site_brand", "config": {"logo_attachment_id": pic, "logo_alt": "로고"}}
    res = await _put(client, admin, layout["id"], 2, {"header": [logo], "top": [{"id": block, **image}]})
    assert (res.status_code, res.json()["errors"][0]["field"]) == (422, "regions.top[0].config"), res.text  # 두 블록에 같은 그림
    res = await _put(client, admin, layout["id"], 2, {"header": [logo], "top": [{"id": block, **H}]})  # 다른 운영자가 옮긴다
    assert res.status_code == 200, res.text
    committed_db.expire_all()
    owner = (await committed_db.execute(select(Attachment.block_id).where(Attachment.id == pic))).scalar_one()
    assert owner == res.json()["regions"]["header"][0]["id"]
