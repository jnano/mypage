"""SEO 데이터(§10) — sitemap·RSS 는 비회원이 읽을 수 있고 색인 허용 게시판의 공개 글만, 글 메타는 색인 대상 글만."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Attachment, BoardGroup
from app.seo import queries
from tests.factories import make_board, make_member, make_post


async def _world(db: AsyncSession):
    author = await make_member(db, level=1)
    free = await make_board(db, slug="free")
    hidden = await make_board(db, slug="hidden", indexable=False)
    members = await make_board(db, slug="members", list_level=2, read_level=2)
    public = await make_post(db, free, author, title="공개 글", content_html="<p>" + "가나다 " * 60 + "</p>")
    await make_post(db, free, author, title="비밀", is_secret=True)
    await make_post(db, free, author, title="가림", is_blinded=True, blind_source="manual")
    await make_post(db, free, author, title="등급", min_view_level=3)
    await make_post(db, hidden, author, title="색인 안 함")
    await make_post(db, members, author, title="회원 전용")
    await db.commit()
    return author, free, public


async def test_sitemap_and_feed_only_public_indexable(committed_db, client) -> None:
    author, free, public = await _world(committed_db)
    index = (await client.get("/api/seo/sitemap")).json()
    assert [b["slug"] for b in index["boards"]] == ["free"] and index["post_parts"] == 1
    posts = (await client.get("/api/seo/sitemap/posts", params={"part": 0})).json()["items"]
    assert [p["id"] for p in posts] == [public.id] and posts[0]["slug"] == "free"
    assert (await client.get("/api/seo/sitemap/posts", params={"part": 1})).json()["items"] == []
    feed = (await client.get("/api/seo/feed")).json()
    assert [i["title"] for i in feed["items"]] == ["공개 글"]
    assert len(feed["items"][0]["description"]) == queries.DESCRIPTION_CHARS and feed["items"][0]["description"].endswith("…")
    assert (await client.get("/api/seo/feed", params={"board": "free"})).json()["board"]["slug"] == "free"
    assert (await client.get("/api/seo/feed", params={"board": "hidden"})).status_code == 404
    assert (await client.get("/api/seo/feed", params={"board": "members"})).status_code == 404


async def test_post_page_seo_block(committed_db, client) -> None:
    author, free, public = await _world(committed_db)
    committed_db.add_all(
        [
            Attachment(post_id=public.id, uploader_id=author.id, role="inline", storage_key="abone.jpg", original_name="a.jpg", sha256="0" * 64,
                       detected_mime="image/jpeg", size_bytes=1, is_image=True, width=2560, height=1440, thumbs_ready=True, visibility="public", sort_order=0),
            Attachment(post_id=public.id, uploader_id=author.id, role="attachment", storage_key="abtwo.jpg", original_name="b.jpg", sha256="1" * 64,
                       detected_mime="image/jpeg", size_bytes=1, is_image=True, width=800, height=600, thumbs_ready=True, visibility="public", sort_order=1, is_cover=True, alt_text="대표"),
        ]
    )  # fmt: skip
    await committed_db.commit()
    seo = (await client.get(f"/api/posts/{public.id}/page")).json()["seo"]
    assert seo["description"].startswith("가나다")
    assert seo["image"] == {"url": "/media/ab/abtwo.w1280.webp", "width": 800, "height": 600, "alt": "대표"}  # 대표 지정 우선, 원본보다 키우지 않는다


async def test_site_settings_public(committed_db, client) -> None:
    body = (await client.get("/api/site")).json()
    assert body["seo"]["site_name"] == "mypage" and body["seo"]["indexable"] is True
    assert body["levels"]["names"]["0"] == "비회원"
    assert "boards:structure" in body["cache"]["tags"]


async def test_site_menu_boards(committed_db, client) -> None:
    """대체 틀의 게시판 메뉴(홈블록 §3.6) — 메뉴 노출·사용 중·비회원 목록 가능만, 분류 그룹 → 게시판 순서."""
    group_b = BoardGroup(name="둘째", sort_order=2)
    group_a = BoardGroup(name="첫째", sort_order=1)
    committed_db.add_all([group_a, group_b])
    await committed_db.flush()
    await make_board(committed_db, slug="b2", name="둘째 묶음", group_id=group_b.id, sort_order=0)
    await make_board(committed_db, slug="a2", name="첫째 묶음 2", group_id=group_a.id, sort_order=2)
    await make_board(committed_db, slug="a1", name="첫째 묶음 1", group_id=group_a.id, sort_order=1)
    await make_board(committed_db, slug="loose", name="묶음 없음", sort_order=5)
    await make_board(committed_db, slug="off", is_active=False)
    await make_board(committed_db, slug="nomenu", show_in_menu=False)
    await make_board(committed_db, slug="members", list_level=2)
    await committed_db.commit()
    menu = (await client.get("/api/site")).json()["menu_boards"]
    assert [b["slug"] for b in menu] == ["loose", "a1", "a2", "b2"]
    assert menu[1] == {"slug": "a1", "name": "첫째 묶음 1"}
