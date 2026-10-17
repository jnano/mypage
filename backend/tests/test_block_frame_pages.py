"""페이지 틀 묶음·주소 집합·개인 틀 — 홈블록 설계도 §5.2·§5.5(B-1·B-2)·§6.2·§13('없는 주소'·'공개 묶음은 비회원 기준')."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.blocks.frame import frame_bundle
from app.core import rate_limit
from app.models import Block, Layout, Page
from tests.factories import make_member
from tests.helpers import as_member, count_queries

pytestmark = pytest.mark.anyio


async def _page(db: AsyncSession, path: str, *, status: str = "published", view_level: int = 0, layout_id: int | None = None) -> int:
    row = Page(path=path, title=f"{path} 제목", status=status, view_level=view_level, layout_id=layout_id,
               published_at=text("now()") if status == "published" else None)  # fmt: skip
    db.add(row)
    await db.flush()
    return row.id


async def _block(db: AsyncSession, *, page_id: int | None = None, layout_id: int | None = None, region: str | None = None, text_: str = "본문", **kw) -> int:
    row = Block(page_id=page_id, layout_id=layout_id, region=region, type="heading", config={"text": text_}, **kw)
    db.add(row)
    await db.flush()
    return row.id


async def _site(db: AsyncSession):
    layout = Layout(name="기본", is_default=True)
    db.add(layout)
    await db.flush()
    await _block(db, layout_id=layout.id, region="header", text_="머리")
    public = await _page(db, "/about")
    await _block(db, page_id=public, text_="소개 본문")
    await _block(db, page_id=public, text_="숨김 본문", is_active=False, sort_order=1)
    await _block(db, page_id=public, text_="회원 본문", audience="member", sort_order=2)
    draft = await _page(db, "/draft", status="draft")
    await _block(db, page_id=draft, text_="초안 본문")
    vip = await _page(db, "/vip", view_level=3)
    await _block(db, page_id=vip, text_="VIP 본문")
    await db.execute(text("INSERT INTO page_path_history (old_path, page_id) VALUES ('/old-about', :p), ('/old-draft', :d)"), {"p": public, "d": draft})
    return layout.id, public, draft, vip


async def test_paths_only_published(client, committed_db) -> None:
    _, public, draft, vip = await _site(committed_db)
    await committed_db.commit()
    body = (await client.get("/api/pages/paths")).json()
    assert body["pages"] == {"/about": {"id": public, "personal": False}, "/vip": {"id": vip, "personal": True}}  # 초안 없음
    assert body["moved"] == {"/old-about": "/about"}  # 초안의 옛 주소도 없음
    assert body["cache"]["tags"] == ["pages:paths"]


async def test_public_page_bundle(db: AsyncSession) -> None:
    layout, public, *_ = await _site(db)
    out = await frame_bundle(db, path="/about")
    assert out["layout"]["id"] == layout and out["layout"]["regions"]["header"][0]["data"]["text"] == "머리"
    page = out["page"]
    assert (page["id"], page["title"], page["draft"]) == (public, "/about 제목", False)
    texts = [b.get("data", {}).get("text") for b in page["blocks"]]
    assert "소개 본문" in texts and "숨김 본문" not in str(out) and "회원 본문" not in str(out)
    assert out["personal_block_ids"] == [b["id"] for b in page["blocks"] if b.get("personal")]
    assert {f"page:{public}", "pages:paths", f"layout:{layout}"} <= set(out["cache"]["tags"])  # 정지점 N-1 ①


async def test_http_public_frame_paths(client, committed_db) -> None:
    await _site(committed_db)
    admin = await make_member(committed_db, level=9, is_admin=True)
    await committed_db.commit()
    assert (await client.get("/api/frame", params={"path": "/about"})).status_code == 200
    for path in ("/draft", "/vip", "/nope", "/About", "/a/b/c/d"):
        assert (await client.get("/api/frame", params={"path": path})).status_code == 404, path
    res = await client.get("/api/frame", params={"path": "/old-about"}, follow_redirects=False)
    assert (res.status_code, res.headers["location"]) == (308, "/api/frame?path=%2Fabout")
    assert (await client.get("/api/frame", params={"path": "/old-draft"})).status_code == 404  # 초안으로 가는 옛 주소는 없음
    # B-2: 공개 묶음은 보는 사람을 읽지 않는다 — 운영자 신분을 실어도 초안은 404, 숨긴 블록은 없다
    res = await client.get("/api/frame", params={"path": "/draft"}, headers=as_member(admin.id))
    assert res.status_code == 404
    assert "숨김 본문" not in (await client.get("/api/frame", params={"path": "/about"}, headers=as_member(admin.id))).text
    assert (await client.get("/api/frame", params={"path": "/about", "route": "search"})).status_code == 422


async def test_viewer_frame(dev_header, client, committed_db) -> None:
    await _site(committed_db)
    low = await make_member(committed_db, level=1)
    high = await make_member(committed_db, level=3)
    admin = await make_member(committed_db, level=9, is_admin=True)
    await committed_db.commit()
    get = lambda who, path, **q: client.get("/api/me/frame", params={"path": path, **q}, headers=as_member(who) if who else {})  # noqa: E731
    assert (await get(None, "/vip")).status_code == 404  # 비회원
    assert (await get(low.id, "/vip")).status_code == 404  # 등급이 모자람 — 있는 줄 모르게
    res = await get(high.id, "/vip")
    assert res.status_code == 200 and res.headers["cache-control"] == "no-store"
    assert res.json()["page"]["blocks"][0]["data"]["text"] == "VIP 본문"
    # 개인 틀은 보는 사람 기준으로 통째로 — 회원 블록이 바로 풀리고(page-state 호출이 필요 없다), 숨김은 운영자에게도 없다
    about = (await get(low.id, "/about")).json()
    assert [b["data"]["text"] for b in about["page"]["blocks"]] == ["소개 본문", "회원 본문"] and about["personal_block_ids"] == []
    # 초안 보기: 운영자만, 'draft' 표시
    assert (await get(low.id, "/draft", draft="true")).status_code == 404
    res = await get(admin.id, "/draft", draft="true")
    assert res.status_code == 200 and res.json()["page"]["draft"] is True
    assert "숨김 본문" not in (await get(admin.id, "/about", draft="true")).text
    assert (await get(admin.id, "/draft")).status_code == 404  # draft 없이는 운영자도 게시된 것만


async def test_draft_view_rate_limit(dev_header, client, committed_db, monkeypatch) -> None:
    await _site(committed_db)
    admin = await make_member(committed_db, level=9, is_admin=True)
    await committed_db.commit()
    monkeypatch.setitem(rate_limit.LIMITS, "frame.draft", rate_limit.Limit(2, 60))
    codes = [(await client.get("/api/me/frame", params={"path": "/draft", "draft": "true"}, headers=as_member(admin.id))).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


async def test_page_bundle_query_budget(db: AsyncSession) -> None:
    await _site(db)
    with count_queries() as q:
        await frame_bundle(db, path="/about")
    assert q["n"] <= 8, q["sql"]
