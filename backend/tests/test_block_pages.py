"""페이지 관리 API — 홈블록 설계도 §3.5·§4.2·§4.6·§4.7·§6.1·§10·§11·§13."""

from urllib.parse import quote

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.viewer import Viewer
from app.blocks import limits
from app.blocks.frame import personal_blocks
from app.files import storage
from app.models import Attachment, ModerationLog, OutboxEvent
from app.worker import handlers  # noqa: F401 — 처리기 등록
from app.worker.core import process_available
from tests.factories import make_member
from tests.helpers import as_member
from tests.test_files import jpeg_with_gps

pytestmark = pytest.mark.anyio
H = {"type": "heading", "config": {"text": "소개"}}


async def _admin(db: AsyncSession) -> int:
    admin = await make_member(db, level=9, is_admin=True)
    await db.commit()
    return admin.id


async def _create(client, admin: int, path: str = "/about", title: str = "소개"):
    return await client.post("/api/admin/pages", json={"path": path, "title": title}, headers=as_member(admin))


async def _put(client, admin: int, page_id: int, version: int | None, **body):
    data = {"path": "/about", "title": "소개"} | body
    headers = as_member(admin) | ({"If-Match": f'"{version}"'} if version is not None else {})
    return await client.put(f"/api/admin/pages/{page_id}", json=data, headers=headers)


async def test_only_admins(dev_header, committed_db, client) -> None:
    user = await make_member(committed_db, level=1)
    await committed_db.commit()
    assert (await client.get("/api/admin/pages", headers=as_member(user.id))).status_code == 403
    assert (await _create(client, user.id)).status_code == 403


@pytest.mark.parametrize("path", ["/About", "/a_b", "/a/b/c/d", "/", "/admin", "/boards/x", "/search", "/media/x", "/_next/x", "/robots.txt"])
async def test_path_rules(dev_header, committed_db, client, path) -> None:
    admin = await _admin(committed_db)
    res = await _create(client, admin, path)
    if path == "/":
        assert res.status_code == 201 and res.json()["is_home"] is True  # 첫 화면
    else:
        assert res.status_code == 422, (path, res.text)


async def test_create_conflict_and_limit(dev_header, committed_db, client, monkeypatch) -> None:
    admin = await _admin(committed_db)
    page = (await _create(client, admin)).json()
    assert page["status"] == "draft" and page["version"] == 1 and page["invalidate"]["now"] == [f"page:{page['id']}", "pages:paths"]
    assert (await _create(client, admin)).json()["code"] == "path_taken"
    monkeypatch.setattr("app.blocks.pages.MAX_PAGES", 1)
    assert (await _create(client, admin, "/other")).json()["code"] == "page_limit"


async def test_save_path_history_and_home(dev_header, committed_db, client) -> None:
    admin = await _admin(committed_db)
    page = (await _create(client, admin)).json()
    assert (await _put(client, admin, page["id"], None)).status_code == 428
    assert (await _put(client, admin, page["id"], 9)).status_code == 412
    res = await _put(client, admin, page["id"], 1, path="/intro", title="  회사 소개 ", blocks=[H])
    assert res.status_code == 200, res.text
    out = res.json()
    assert (out["path"], out["title"], out["old_paths"], out["version"]) == ("/intro", "회사 소개", ["/about"], 2)
    assert out["content_updated_at"] is not None and out["blocks"][0]["type"] == "heading"
    # 옛 주소로 되돌리면 그 옛 기록은 사라지고 지금 주소가 옛 기록이 된다
    out = (await _put(client, admin, page["id"], 2, path="/about", title="회사 소개")).json()
    assert (out["path"], out["old_paths"]) == ("/about", ["/intro"])
    # 최근 10개만
    version = out["version"]
    for i in range(12):
        version = (await _put(client, admin, page["id"], version, path=f"/p{i}", title="회사 소개")).json()["version"]
    count = (await committed_db.execute(text("SELECT count(*) FROM page_path_history WHERE page_id = :p"), {"p": page["id"]})).scalar_one()
    assert count == limits.PATH_HISTORY_PER_PAGE
    home = (await _create(client, admin, "/", "처음")).json()
    assert (await _put(client, admin, home["id"], 1, path="/home", title="처음")).json()["code"] == "home_page"
    assert (await _put(client, admin, page["id"], version, path="/", title="x")).status_code in (409, 422)


async def test_page_blocks_and_label_conflicts(dev_header, committed_db, client) -> None:
    admin = await _admin(committed_db)
    menu = (await committed_db.execute(text("INSERT INTO menus (name) VALUES ('주 메뉴') RETURNING id"))).scalar_one()
    await committed_db.commit()
    layout = (await client.post("/api/admin/layouts", json={"name": "기본"}, headers=as_member(admin))).json()
    await client.post(f"/api/admin/layouts/{layout['id']}/default", headers=as_member(admin))
    nav = {"type": "menu", "config": {"menu_id": menu, "label": "주 메뉴"}}
    assert (await client.put(f"/api/admin/layouts/{layout['id']}", json={"name": "기본", "regions": {"nav": [nav]}}, headers=as_member(admin) | {"If-Match": '"1"'})).status_code == 200
    page = (await _create(client, admin)).json()
    columns = {"type": "columns", "config": {"count": 2}, "children": [{**H, "column_index": 0}, {**H, "column_index": 1}]}
    assert (await _put(client, admin, page["id"], 1, blocks=[columns])).status_code == 200  # 칸 나누기는 페이지에
    # 페이지가 쓸 틀(기본 틀)의 이름과 겹치면 422 — 한 화면에 같은 이름의 nav 둘(§10, v7 N-3)
    landmark = {"type": "group", "config": {"title": "주 메뉴", "landmark": True}, "children": [H]}  # 페이지에 놓는 이름 있는 블록
    res = await _put(client, admin, page["id"], 2, blocks=[landmark])
    assert res.status_code == 422 and "주 메뉴" in res.json()["errors"][0]["message"]
    landmark["config"]["title"] = "새 소식"
    assert (await _put(client, admin, page["id"], 2, blocks=[landmark])).status_code == 200
    # 거꾸로: 틀을 고쳐 그 틀을 쓰는 페이지의 이름과 겹치게 하면 422
    clash = {"type": "breadcrumb", "config": {"menu_id": menu, "label": "새 소식"}}
    res = await client.put(f"/api/admin/layouts/{layout['id']}", json={"name": "기본", "regions": {"nav": [nav], "top": [clash]}}, headers=as_member(admin) | {"If-Match": '"2"'})
    assert res.status_code == 422 and "/about" in res.json()["errors"][0]["message"]
    assert (await _put(client, admin, page["id"], 3, layout_id=999999)).json()["code"] == "dangling_ref"


async def test_publish_and_delete_rules(dev_header, committed_db, client) -> None:
    admin = await _admin(committed_db)
    page = (await _create(client, admin)).json()
    out = (await client.post(f"/api/admin/pages/{page['id']}/publish", headers=as_member(admin))).json()
    first = out["published_at"]
    assert out["status"] == "published" and first is not None
    out = (await client.post(f"/api/admin/pages/{page['id']}/unpublish", headers=as_member(admin))).json()
    assert out["status"] == "draft" and out["published_at"] == first  # 처음 게시 시각은 남는다
    menu = (await committed_db.execute(text("INSERT INTO menus (name) VALUES ('주 메뉴') RETURNING id"))).scalar_one()
    item = (await committed_db.execute(text("INSERT INTO menu_items (menu_id, label, link_kind, page_id) VALUES (:m, '소개', 'page', :p) RETURNING id"), {"m": menu, "p": page["id"]})).scalar_one()
    await committed_db.commit()
    res = await client.delete(f"/api/admin/pages/{page['id']}", headers=as_member(admin))
    assert (res.status_code, res.json()["code"], res.json()["errors"][0]["field"]) == (409, "in_menu", f"menu_items.{item}")
    await committed_db.execute(text("DELETE FROM menus"))
    await committed_db.commit()
    assert (await client.delete(f"/api/admin/pages/{page['id']}", headers=as_member(admin))).status_code == 200
    home = (await _create(client, admin, "/", "처음")).json()
    assert (await client.delete(f"/api/admin/pages/{home['id']}", headers=as_member(admin))).json()["code"] == "home_page"
    actions = set((await committed_db.execute(select(ModerationLog.action).where(ModerationLog.target_type == "page"))).scalars())
    assert {"page.create", "page.publish", "page.unpublish", "page.delete"} <= actions


async def test_personal_blocks_respect_page_read(db: AsyncSession) -> None:
    """페이지 블록의 회원 블록 — 주인 페이지의 page.read(게시 ∧ 열람 등급)도 본다(§6.1, 정지점 N-1)"""
    from app.models import Block, Page

    member = await make_member(db, level=1)
    draft = Page(path="/draft", title="초안")
    leveled = Page(path="/vip", title="등급", status="published", published_at=text("now()"), view_level=3)
    db.add_all([draft, leveled])
    await db.flush()
    a = Block(page_id=draft.id, type="heading", config={"text": "초안 회원 블록"}, audience="member")
    b = Block(page_id=leveled.id, type="heading", config={"text": "등급 페이지 회원 블록"}, audience="member")
    db.add_all([a, b])
    await db.flush()
    viewer = Viewer(member_id=member.id, level=1)
    assert await personal_blocks(db, viewer, [a.id, b.id]) == {}
    assert set(await personal_blocks(db, Viewer(member_id=member.id, level=3), [a.id, b.id])) == {b.id}
    assert set(await personal_blocks(db, Viewer(member_id=member.id, level=0, is_admin=True), [a.id, b.id])) == {a.id, b.id}


async def test_page_images_follow_publish(dev_header, committed_db, client) -> None:
    admin = await _admin(committed_db)
    headers = as_member(admin) | {"X-Upload-Filename": quote("소개.jpg"), "Content-Type": "application/octet-stream"}
    att = (await client.post("/api/uploads?target=site", content=jpeg_with_gps(), headers=headers)).json()["attachment"]["id"]
    await process_available(50)
    page = (await _create(client, admin)).json()
    image = {"type": "image", "config": {"attachment_id": att, "alt": "사무실"}}
    assert (await _put(client, admin, page["id"], 1, blocks=[image])).status_code == 200
    await process_available(50)
    row = lambda: committed_db.execute(select(Attachment).where(Attachment.id == att))  # noqa: E731
    committed_db.expire_all()
    assert (await row()).scalar_one().visibility == "private"  # 초안 페이지 — 공개 저장소에 가지 않는다
    assert (await client.get(f"/api/attachments/{att}/thumb")).status_code == 404
    await client.post(f"/api/admin/pages/{page['id']}/publish", headers=as_member(admin))
    await process_available(50)
    committed_db.expire_all()
    r = (await row()).scalar_one()
    assert r.visibility == "public" and storage.locate(r.storage_key)[0] == "public"
    revalidated = (await committed_db.execute(select(OutboxEvent.payload).where(OutboxEvent.type == "cache.revalidate"))).scalars().all()
    assert any(f"page:{page['id']}" in p["now"] for p in revalidated)  # 작업자가 페이지 태그도 만료(정지점 N-1)
    await client.post(f"/api/admin/pages/{page['id']}/unpublish", headers=as_member(admin))
    committed_db.expire_all()
    assert (await row()).scalar_one().visibility == "private"  # 비게시는 저장 순간 비공개 표시(좁히는 쪽 먼저)
    await client.post(f"/api/admin/pages/{page['id']}/publish", headers=as_member(admin))
    await process_available(50)
    assert (await client.delete(f"/api/admin/pages/{page['id']}", headers=as_member(admin))).status_code == 200
    committed_db.expire_all()
    r = (await row()).scalar_one()
    assert (r.block_id, r.visibility) == (None, "private")  # 페이지와 함께 떨어진 그림도 바로 비공개


async def test_reserved_conflicts(dev_header, committed_db, client) -> None:
    """예약 첫 단과 겹친 페이지(새 라우트 배포로 예약어가 늘어난 경우 — DB 에는 들어갈 수 있다)는 목록에 알린다(§11)"""
    admin = await _admin(committed_db)
    await committed_db.execute(text("INSERT INTO pages (path, title) VALUES ('/search/help', '도움말')"))
    await committed_db.commit()
    body = (await client.get("/api/admin/pages", headers=as_member(admin))).json()
    assert [c["path"] for c in body["reserved_conflicts"]] == ["/search/help"]
