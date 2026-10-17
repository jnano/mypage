"""블록 편집 보조 API — 홈블록 설계도 §3.6(기본 틀 만들기)·§4.4(끊긴 참조)·§7·§8(블록 종류·미리보기)·§10(기본 틀 바꾸기 경고)."""

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.blocks import schema
from app.blocks import types as t
from app.blocks.frame import frame_bundle
from app.core import rate_limit
from app.models import Attachment, Block, Layout, Menu, MenuItem, ModerationLog
from tests.factories import make_board, make_member
from tests.helpers import as_member

pytestmark = pytest.mark.anyio


async def _admin(db: AsyncSession) -> int:
    admin = await make_member(db, level=9, is_admin=True)
    await db.commit()
    return admin.id


async def test_only_admins(dev_header, committed_db, client) -> None:
    user = await make_member(committed_db, level=1)
    await committed_db.commit()
    h = as_member(user.id)
    assert (await client.get("/api/admin/block-types", headers=h)).status_code == 403
    assert (await client.post("/api/admin/blocks/preview", json={"owner": "page"}, headers=h)).status_code == 403
    assert (await client.get("/api/admin/blocks/dangling", headers=h)).status_code == 403
    assert (await client.post("/api/admin/layouts/bootstrap", headers=h)).status_code == 403


# ── 블록 종류(설정 폼 형식) ──────────────────────────────


def _props(node):
    """형식 안의 모든 칸(중첩 $defs 포함)"""
    if isinstance(node, dict):
        for name, prop in (node.get("properties") or {}).items():
            yield name, prop
        for v in node.values():
            yield from _props(v)
    elif isinstance(node, list):
        for v in node:
            yield from _props(v)


def test_every_field_has_a_name() -> None:
    """종류·모듈의 모든 칸에 사람이 읽을 이름이 있다 — 칸을 더하고 이름을 빠뜨리면 form_schema 가 예외(§8)"""
    out = schema.block_types()
    listed = {i["type"] for i in out["types"]}
    assert listed == set(t.SPECS) - {"outlet"}  # 본문 자리는 운영자가 더하지 않는다
    for item in out["types"]:
        assert ("schema" in item) == (t.SPECS[item["type"]].available and t.SPECS[item["type"]].model is not None)
    fields = [p for item in out["types"] if "schema" in item for _, p in _props(item["schema"])]
    fields += [p for m in out["modules"].values() for _, p in _props(m["schema"])]
    assert fields and all(p["title"] and not p["title"].isascii() for p in fields)  # 영문 기본 이름이 남지 않는다
    def objects(node):
        if isinstance(node, dict):
            if "properties" in node:
                yield node
            for v in node.values():
                yield from objects(v)
        elif isinstance(node, list):
            for v in node:
                yield from objects(v)

    schemas = [i["schema"] for i in out["types"] if "schema" in i] + [m["schema"] for m in out["modules"].values()]
    assert not [o for s in schemas for o in objects(s) if "description" in o]  # 모델 docstring(개발자 주석)이 나가지 않는다


def test_missing_name_fails() -> None:
    """대조군 — 이름 없는 칸이 있는 모델은 형식을 만들지 못한다"""
    from pydantic import BaseModel

    class Odd(BaseModel):
        brand_new_field: int

    with pytest.raises(KeyError):
        schema.form_schema(Odd)


def test_widgets_and_help() -> None:
    types = {i["type"]: i for i in schema.block_types()["types"]}
    props = dict(_props(types["image"]["schema"]))
    assert props["attachment_id"]["x-widget"] == "image" and props["page_id"]["x-widget"] == "page"
    assert dict(_props(types["recent_posts"]["schema"]))["board_ids"]["x-widget"] == "boards"
    assert dict(_props(types["text"]["schema"]))["source"]["x-widget"] == "markdown"
    assert "최근 글 100개" in types["recent_comments"]["help"]  # 코드 검토 v8 N-1 — 최근 댓글의 뜻
    assert types["popup"]["available"] is False and "schema" not in types["popup"]


# ── 미리보기 ─────────────────────────────────────────────


async def test_preview_guest_and_member_view(dev_header, committed_db, client) -> None:
    admin = await _admin(committed_db)
    image = Attachment(uploader_id=admin, original_name="그림.png", storage_key="pv-1", sha256="0" * 64, detected_mime="image/png",
                       size_bytes=10, is_image=True, width=10, height=10)  # fmt: skip
    committed_db.add(image)
    await committed_db.commit()
    body = {
        "owner": "page",
        "blocks": [
            {"type": "heading", "config": {"text": "안내"}},
            {"type": "heading", "config": {"text": "회원 안내"}, "audience": "member"},
            {"type": "image", "config": {"attachment_id": image.id, "alt": "사진"}},
            {"type": "heading", "config": {"text": "숨김"}, "is_active": False},
        ],
    }
    res = await client.post("/api/admin/blocks/preview", json=body, headers=as_member(admin))
    assert res.status_code == 200, res.text
    out = res.json()
    texts = [b.get("data", {}).get("text") for b in out["blocks"]]
    assert texts[0] == "안내" and "숨김" not in res.text
    member_slot = out["blocks"][1]
    assert member_slot.get("personal") is True and "data" not in member_slot  # 비회원이 보는 모습 — 회원 블록은 자리만
    assert out["blocks"][2]["data"]["image"]["alt"] == "사진"  # 저장 전 그림(block_id 없음)도 보인다
    assert all(b["id"] < 0 for b in out["blocks"])  # 새 블록은 임시 id
    res = await client.post("/api/admin/blocks/preview", json=body | {"as_member": True}, headers=as_member(admin))
    assert [b["data"]["text"] for b in res.json()["blocks"] if b["type"] == "heading"] == ["안내", "회원 안내"]
    assert (await committed_db.execute(select(Block.id))).first() is None  # 아무것도 저장하지 않는다


async def test_preview_validates_like_save(dev_header, committed_db, client) -> None:
    admin = await _admin(committed_db)
    bad = {"owner": "layout", "regions": {"header": [{"type": "heading", "config": {"text": " "}}], "middle": []}}
    res = await client.post("/api/admin/blocks/preview", json=bad, headers=as_member(admin))
    assert res.status_code == 422 and res.json()["errors"][0]["field"] == "regions.middle"
    bad = {"owner": "layout", "regions": {"header": [{"type": "heading", "config": {"text": " "}}]}}
    res = await client.post("/api/admin/blocks/preview", json=bad, headers=as_member(admin))
    assert res.status_code == 422 and res.json()["errors"][0]["field"].startswith("regions.header[0].config")
    res = await client.post("/api/admin/blocks/preview", json={"owner": "page", "blocks": [{"type": "account"}]}, headers=as_member(admin))
    assert res.status_code == 422  # 페이지에 놓을 수 없는 블록 — 저장과 같은 검증


async def test_preview_rate_limit(dev_header, committed_db, client, monkeypatch) -> None:
    admin = await _admin(committed_db)
    monkeypatch.setitem(rate_limit.LIMITS, "blocks.preview", rate_limit.Limit(2, 60))
    codes = [(await client.post("/api/admin/blocks/preview", json={"owner": "page"}, headers=as_member(admin))).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


# ── 끊긴 참조 ────────────────────────────────────────────


async def test_dangling(dev_header, committed_db, client) -> None:
    admin = await _admin(committed_db)
    gone = await make_board(committed_db, slug="gone")
    kept = await make_board(committed_db, slug="kept")
    layout = Layout(name="기본", is_default=True)
    committed_db.add(layout)
    await committed_db.flush()
    committed_db.add_all([
        Block(layout_id=layout.id, region="aside", type="board_links", config={"board_ids": [kept.id, gone.id]}),
        Block(layout_id=layout.id, region="aside", type="board_links", config={"board_ids": [kept.id]}),
        Block(layout_id=layout.id, region="nav", type="menu", config={"menu_id": 999_999, "label": "주 메뉴"}),
        Block(layout_id=layout.id, region="top", type="image", config={"attachment_id": 999_998, "alt": "사진"}),
        Block(layout_id=layout.id, region="top", type="heading", config={"text": "x", "level": 9}),  # 형식이 바뀐 뒤 남은 행 꼴
    ])  # fmt: skip
    await committed_db.execute(text("INSERT INTO pages (path, title) VALUES ('/search/old', '가려진 페이지')"))
    await committed_db.commit()
    await committed_db.execute(text("DELETE FROM boards WHERE id = :b"), {"b": gone.id})
    await committed_db.commit()
    res = await client.get("/api/admin/blocks/dangling", headers=as_member(admin))
    body = res.json()
    by_type = {b["type"]: b for b in body["blocks"]}
    assert len(body["blocks"]) == 4  # 끊김 없는 바로가기는 없다
    assert by_type["board_links"]["missing"] == {"boards": [gone.id]} and by_type["board_links"]["owner"] == {"kind": "layout", "id": layout.id, "name": "기본"}
    assert by_type["menu"]["missing"] == {"menus": [999_999]} and by_type["image"]["missing"] == {"attachments": [999_998]}
    assert by_type["heading"]["invalid"] is True
    assert [p["path"] for p in body["reserved_conflicts"]] == ["/search/old"]
    badges = (await client.get("/api/admin/summary", headers=as_member(admin))).json()["badges"]
    assert (badges["broken_blocks"], badges["reserved_pages"]) == (4, 1)


# ── 기본 틀 만들기 ───────────────────────────────────────


async def test_bootstrap(dev_header, committed_db, client) -> None:
    admin = await _admin(committed_db)
    first = await make_board(committed_db, slug="b-first", name="공지")
    await make_board(committed_db, slug="b-hidden", name="숨김", show_in_menu=False)
    await make_board(committed_db, slug="b-member", name="회원", list_level=2)
    committed_db.add(Menu(name="주 메뉴"))  # 운영자가 먼저 만든 같은 이름 — 덮지 않는다
    await committed_db.commit()
    res = await client.post("/api/admin/layouts/bootstrap", headers=as_member(admin))
    assert res.status_code == 201, res.text
    out = res.json()
    assert "layouts:bindings" in str(out["invalidate"])
    menu = await committed_db.get(Menu, out["menu_id"])
    assert menu.name == "주 메뉴 (2)"
    items = (await committed_db.execute(select(MenuItem.label, MenuItem.board_id).where(MenuItem.menu_id == menu.id).order_by(MenuItem.sort_order))).all()
    assert [i.label for i in items] == ["처음", "공지", "검색", "알림"] and items[1].board_id == first.id  # 메뉴 노출·비회원 목록 가능만
    bundle = await frame_bundle(committed_db)
    header = [b["type"] for b in bundle["layout"]["regions"]["header"]]
    assert header == ["site_brand", "menu", "search_box", "account"] and bundle["layout"]["regions"]["footer"][0]["type"] == "footer_info"
    assert bundle["layout"]["regions"]["header"][1]["data"]["label"] == "사이트"  # 대체 틀과 같은 탐색 이름
    actions = set((await committed_db.execute(select(ModerationLog.action))).scalars())
    assert {"menu.create", "layout.bootstrap"} <= actions
    again = await client.post("/api/admin/layouts/bootstrap", headers=as_member(admin))
    assert (again.status_code, again.json()["code"]) == (409, "default_exists")


# ── 기본 틀 바꾸기 경고(코드 검토 v11 N-2) ───────────────


async def test_set_default_warns_about_unbound_pages(dev_header, committed_db, client) -> None:
    admin = await _admin(committed_db)
    old = Layout(name="옛 기본", is_default=True)
    new = Layout(name="새 틀")
    committed_db.add_all([old, new])
    await committed_db.flush()
    menu = Menu(name="m")
    committed_db.add(menu)
    await committed_db.flush()
    committed_db.add(Block(layout_id=new.id, region="aside", type="group", config={"title": "안내", "landmark": True}))
    page = (await committed_db.execute(text("INSERT INTO pages (path, title) VALUES ('/p', 'p') RETURNING id"))).scalar_one()
    committed_db.add(Block(page_id=page, type="group", config={"title": "안내", "landmark": True}))
    await committed_db.commit()
    res = await client.post(f"/api/admin/layouts/{new.id}/default", headers=as_member(admin))
    assert res.status_code == 200
    [warning] = res.json()["warnings"]
    assert "/p" in warning["message"] and "안내" in warning["message"]
    res = await client.post(f"/api/admin/layouts/{old.id}/default", headers=as_member(admin))
    assert res.json()["warnings"] == []  # 대조: 겹치지 않는 틀로 돌리면 경고 없음


async def test_preview_checks_names_with_the_other_owner(dev_header, committed_db, client) -> None:
    """미리보기도 저장처럼 같은 화면의 이름표 겹침을 본다(코드 검토 v15 N-3 a) — 페이지 ↔ 그 틀, 틀 ↔ 그 틀을 쓰는 페이지"""
    admin = await _admin(committed_db)
    layout = Layout(name="기본", is_default=True)
    committed_db.add(layout)
    await committed_db.flush()
    committed_db.add(Block(layout_id=layout.id, region="aside", type="group", config={"title": "안내", "landmark": True}))
    page = (await committed_db.execute(text("INSERT INTO pages (path, title) VALUES ('/p', 'p') RETURNING id"))).scalar_one()
    committed_db.add(Block(page_id=page, type="group", config={"title": "소개", "landmark": True}))
    await committed_db.commit()
    group = lambda title: {"type": "group", "config": {"title": title, "landmark": True}}  # noqa: E731
    res = await client.post("/api/admin/blocks/preview", json={"owner": "page", "blocks": [group("안내")]}, headers=as_member(admin))
    assert res.status_code == 422 and "틀 " in res.text  # 페이지가 쓸 틀(기본 틀)의 이름과 겹침
    regions = {"aside": [group("소개")]}
    res = await client.post("/api/admin/blocks/preview", json={"owner": "layout", "regions": regions, "layout_id": layout.id}, headers=as_member(admin))
    assert res.status_code == 422 and "/p" in res.text
    res = await client.post("/api/admin/blocks/preview", json={"owner": "layout", "regions": regions}, headers=as_member(admin))
    assert res.status_code == 200  # 대조: 새 틀(쓰는 페이지 없음)이면 통과
