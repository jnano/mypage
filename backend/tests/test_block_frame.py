"""틀 묶음(GET /api/frame) — 홈블록 설계도 §5.2·§5.5·§6.1·§13('공개 판정 ↔ can()'·'쿼리·호출 수')."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.viewer import GUEST
from app.blocks.frame import frame_bundle
from app.models import Block, Comment, Layout, Post
from app.permissions import NO_ROLE, can
from tests.factories import make_board, make_member, make_post
from tests.helpers import count_queries

pytestmark = pytest.mark.anyio
NOW = datetime.now(UTC)


async def _layout(db: AsyncSession, name: str = "기본", *, default: bool = True) -> int:
    row = Layout(name=name, is_default=default)
    db.add(row)
    await db.flush()
    return row.id


async def _block(db: AsyncSession, layout_id: int, region: str | None, type_: str, config: dict, *, parent: int | None = None,
                 order: int = 0, **kw) -> int:  # fmt: skip
    row = Block(layout_id=layout_id, region=region if parent is None else None, parent_id=parent, type=type_, config=config, sort_order=order, **kw)
    db.add(row)
    await db.flush()
    return row.id


def _flat(bundle: dict) -> list[dict]:
    out = []

    def walk(nodes):
        for n in nodes:
            out.append(n)
            walk(n.get("children", []))

    for nodes in (bundle["layout"] or {}).get("regions", {}).values():
        walk(nodes)
    return out


async def test_no_layout_means_fallback(db: AsyncSession) -> None:
    out = await frame_bundle(db, route="search")
    assert out["layout"] is None and out["personal_block_ids"] == []
    assert "layouts:bindings" in out["cache"]["tags"]


async def test_owner_choice_board_then_route_then_default(db: AsyncSession) -> None:
    default = await _layout(db, "기본")
    for_boards = await _layout(db, "게시판", default=False)
    for_free = await _layout(db, "자유", default=False)
    board = await make_board(db, slug="free")
    await make_board(db, slug="notice")
    await db.execute(text("INSERT INTO layout_bindings (route_class, layout_id) VALUES ('board', :l)"), {"l": for_boards})
    assert (await frame_bundle(db))["layout"]["id"] == default
    assert (await frame_bundle(db, route="search"))["layout"]["id"] == default  # 대응 없음
    assert (await frame_bundle(db, board_slug="notice"))["layout"]["id"] == for_boards
    assert (await frame_bundle(db, board_slug="nope"))["layout"]["id"] == for_boards  # 없는 게시판도 화면 종류의 틀
    board.layout_id = for_free
    await db.flush()
    out = await frame_bundle(db, board_slug="free")
    assert out["layout"]["id"] == for_free
    assert {"layout:%d" % for_free, "boards:structure", "layouts:bindings", "settings:seo"} <= set(out["cache"]["tags"])


async def test_visibility_of_blocks(db: AsyncSession) -> None:
    lid = await _layout(db)
    shown = await _block(db, lid, "top", "heading", {"text": "모두"})
    await _block(db, lid, "top", "heading", {"text": "숨김"}, is_active=False, order=1)
    member = await _block(db, lid, "top", "heading", {"text": "회원만"}, audience="member", order=2)
    leveled = await _block(db, lid, "top", "heading", {"text": "등급"}, min_level=3, order=3)
    guest = await _block(db, lid, "top", "heading", {"text": "가입 안내"}, audience="guest", order=4)
    group = await _block(db, lid, "aside", "group", {"title": "회원 묶음"}, audience="member")
    await _block(db, lid, None, "heading", {"text": "회원 묶음 안"}, parent=group)
    out = await frame_bundle(db)
    nodes = {n["id"]: n for n in _flat(out)}
    assert nodes[shown]["data"] == {"text": "모두", "level": 2}
    assert nodes[member] == {"id": member, "type": "heading", "personal": True}  # 내용 없이 자리만
    assert nodes[leveled]["personal"] and "data" not in nodes[leveled]
    assert nodes[guest]["audience"] == "guest" and nodes[guest]["data"]["text"] == "가입 안내"
    assert nodes[group] == {"id": group, "type": "group", "personal": True}  # 자식은 page-state 가 함께
    assert "숨김" not in str(out)  # 숨긴 블록은 공개 응답에 없다(운영자에게도 — B-2)
    assert set(out["personal_block_ids"]) == {member, leveled, group}


async def test_recent_posts_match_can_guest_read(db: AsyncSession) -> None:
    """공개 판정 ↔ can(): 최근 글 블록에 나온 글 = 비회원이 열 수 있는 글(∧ 만료 안 됨). 판정 하나를 뒤집으면 실패한다"""
    author = await make_member(db)
    board = await make_board(db, slug="free")
    posts = {
        "보통": await make_post(db, board, author),
        "비밀": await make_post(db, board, author, is_secret=True),
        "가림": await make_post(db, board, author, is_blinded=True),
        "등급": await make_post(db, board, author, min_view_level=2),
        "대기": await make_post(db, board, author, status="pending"),
        "임시": await make_post(db, board, author, status="draft"),
        "만료": await make_post(db, board, author, expires_at=NOW - timedelta(days=1)),
        "고정": await make_post(db, board, author, is_pinned=True, pin_order=1),
    }
    lid = await _layout(db)
    bid = await _block(db, lid, "aside", "recent_posts", {"board_ids": [board.id], "count": 20})
    out = await frame_bundle(db)
    got = {i["id"] for i in _flat(out)[0]["data"]["items"]}
    rows = {p.id: p for p in (await db.execute(select(Post).where(Post.board_id == board.id))).scalars()}
    expected = {i for i, p in rows.items() if can(GUEST, NO_ROLE, "post.read", board, p) and not (p.expires_at and p.expires_at <= NOW)}
    assert got == expected == {posts["보통"].id, posts["고정"].id}
    items = _flat(out)[0]["data"]["items"]
    assert items[0]["id"] == posts["고정"].id and items[0]["pinned"]  # 고정 글은 앞(§4.4)
    assert items[1]["href"] == f"/boards/free/{posts['보통'].id}"
    assert {"recent:posts", "boards:structure"} <= set(out["cache"]["tags"])
    assert bid not in out["personal_block_ids"]


async def test_recent_posts_order_count_and_pinned_off(db: AsyncSession) -> None:
    author = await make_member(db)
    a = await make_board(db, slug="a")
    b = await make_board(db, slug="b")
    for i in range(4):
        await make_post(db, a, author, title=f"a{i}", published_at=NOW - timedelta(hours=10 - i))
        await make_post(db, b, author, title=f"b{i}", published_at=NOW - timedelta(hours=10 - i, minutes=30))
    await make_post(db, a, author, title="고정", is_pinned=True, pin_order=1)
    lid = await _layout(db)
    await _block(db, lid, "top", "recent_posts", {"board_ids": [a.id, b.id], "count": 3, "include_pinned": False})
    await _block(db, lid, "top", "recent_posts", {"board_ids": [b.id], "count": 2, "view": "photo"}, order=1)
    out = await frame_bundle(db)
    first, second = _flat(out)
    assert [i["title"] for i in first["data"]["items"]] == ["a3", "b3", "a2"]  # 두 게시판을 합쳐 최신순, 고정 글 빠짐
    assert [i["title"] for i in second["data"]["items"]] == ["b3", "b2"]
    assert second["data"]["view"] == "photo" and second["data"]["items"][0]["image"] is None  # 대표 사진 없음 → 자리 표시


async def test_member_only_board_makes_dynamic_block_personal(db: AsyncSession) -> None:
    author = await make_member(db)
    public = await make_board(db, slug="free")
    members = await make_board(db, slug="members", read_level=1)
    await make_post(db, members, author, title="회원 글")
    lid = await _layout(db)
    mixed = await _block(db, lid, "top", "recent_posts", {"board_ids": [public.id, members.id]})
    links = await _block(db, lid, "top", "board_links", {"board_ids": [members.id]}, order=1)
    out = await frame_bundle(db)
    assert "회원 글" not in str(out)  # 회원 전용 게시판의 글이 공개 캐시에 섞이지 않는다(P1)
    assert mixed in out["personal_block_ids"]
    assert links not in out["personal_block_ids"]  # 목록은 비회원도 볼 수 있다(list_level 0) — 이름·주소만
    hidden = await make_board(db, slug="hidden", list_level=1)
    await db.execute(text("UPDATE blocks SET config = :c WHERE id = :b"), {"c": f'{{"board_ids": [{hidden.id}]}}', "b": links})
    assert links in (await frame_bundle(db))["personal_block_ids"]


async def test_recent_comments(db: AsyncSession) -> None:
    author = await make_member(db)
    board = await make_board(db, slug="free")
    open_post = await make_post(db, board, author, title="열린 글")
    secret = await make_post(db, board, author, is_secret=True)
    for post, content, kw in (
        (open_post, "  보이는\n댓글 " + "가" * 100, {}),
        (open_post, "가린 댓글", {"is_blinded": True}),
        (open_post, "지운 댓글", {"status": "deleted"}),
        (secret, "비밀 글의 댓글", {}),
    ):
        db.add(Comment(post_id=post.id, member_id=author.id, author_name_snapshot="작성자", content=content, **kw))
    await db.flush()
    lid = await _layout(db)
    await _block(db, lid, "aside", "recent_comments", {"board_ids": [board.id]})
    items = _flat(await frame_bundle(db))[0]["data"]["items"]
    assert len(items) == 1 and items[0]["post_title"] == "열린 글"
    assert items[0]["excerpt"].startswith("보이는 댓글 가") and len(items[0]["excerpt"]) == 80
    assert items[0]["href"] == f"/boards/free/{open_post.id}#c-{items[0]['id']}"


async def test_board_links_and_menus(db: AsyncSession) -> None:
    author = await make_member(db)
    free = await make_board(db, slug="free", name="자유게시판")
    members = await make_board(db, slug="members", list_level=1)
    await make_post(db, free, author, published_at=NOW - timedelta(hours=1))
    menu = (await db.execute(text("INSERT INTO menus (name) VALUES ('주 메뉴') RETURNING id"))).scalar_one()
    await db.execute(
        text(
            "INSERT INTO menu_items (menu_id, sort_order, label, link_kind, board_id, url, min_level) VALUES"
            " (:m, 0, '자유', 'board', :f, NULL, 0), (:m, 1, '회원 게시판', 'board', :g, NULL, 0), (:m, 2, '등급', 'url', NULL, '/x', 2)"
        ),
        {"m": menu, "f": free.id, "g": members.id},
    )
    lid = await _layout(db)
    links = await _block(db, lid, "aside", "board_links", {"board_ids": [free.id]})
    nav = await _block(db, lid, "nav", "menu", {"menu_id": menu, "label": "주 메뉴"})
    out = await frame_bundle(db)
    nodes = {n["id"]: n for n in _flat(out)}
    item = nodes[links]["data"]["items"][0]
    assert (item["name"], item["href"]) == ("자유게시판", "/boards/free") and item["last_posted_at"] is not None
    # 비회원에게는 자기가 볼 수 있는 항목만 — 등급 항목·회원 게시판 링크는 빠지고 '회원이면 다시'(§6.1)
    assert [i["label"] for i in nodes[nav]["data"]["items"]] == ["자유"]
    assert nodes[nav]["refresh"] and nav in out["personal_block_ids"]
    assert f"menu:{menu}" in out["cache"]["tags"]


async def test_query_budget_at_max_config(db: AsyncSession) -> None:
    """틀 묶음 하나당 쿼리 ≤ 8 — 모든 종류를 담은 최대 구성(§5.2·§12)"""
    author = await make_member(db)
    boards = [await make_board(db, slug=f"b{i}") for i in range(10)]
    for b in boards[:3]:
        post = await make_post(db, b, author)
        db.add(Comment(post_id=post.id, member_id=author.id, author_name_snapshot="작성자", content="댓글"))
    menu = (await db.execute(text("INSERT INTO menus (name) VALUES ('주 메뉴') RETURNING id"))).scalar_one()
    await db.execute(text("INSERT INTO menu_items (menu_id, label, link_kind, url) VALUES (:m, '공지', 'url', '/n')"), {"m": menu})
    page = (await db.execute(text("INSERT INTO pages (path, title, status, published_at) VALUES ('/about', '소개', 'published', now()) RETURNING id"))).scalar_one()
    lid = await _layout(db)
    ids = [b.id for b in boards]
    await _block(db, lid, "header", "site_brand", {})
    await _block(db, lid, "nav", "menu", {"menu_id": menu, "label": "주 메뉴"})
    await _block(db, lid, "aside", "sub_menu", {"menu_id": menu, "label": "옆 메뉴"})
    await _block(db, lid, "top", "breadcrumb", {"menu_id": menu})
    for i in range(4):
        await _block(db, lid, "top", "recent_posts", {"board_ids": ids, "count": 20}, order=10 + i)
        await _block(db, lid, "top", "recent_comments", {"board_ids": ids, "count": 20}, order=20 + i)
    await _block(db, lid, "top", "board_links", {"board_ids": ids}, order=30)
    await _block(db, lid, "top", "buttons", {"items": [{"label": "소개", "link": {"kind": "page", "page_id": page}}]}, order=31)
    await _block(db, lid, "top", "text", {"source": "**안내**"}, order=32)
    await _block(db, lid, "footer", "footer_info", {"copyright": "© 예시"})
    await db.flush()
    with count_queries() as q:
        out = await frame_bundle(db, board_slug="b0")
    assert q["n"] <= 8, q["sql"]
    assert len(_flat(out)) == 16  # 사이트 4 + 동적 8 + 게시판 바로가기·단추·글·바닥 정보


async def test_http_frame(client, committed_db) -> None:
    lid = await _layout(committed_db)
    await _block(committed_db, lid, "top", "heading", {"text": "안내"})
    await committed_db.commit()
    res = await client.get("/api/frame", params={"route": "search"})
    assert res.status_code == 200 and res.json()["layout"]["regions"]["top"][0]["data"]["text"] == "안내"
    assert (await client.get("/api/frame", params={"route": "page"})).status_code == 422
    assert (await client.get("/api/frame", params={"route": "search", "board": "free"})).status_code == 422


async def test_guest_board_clauses_match_can(db: AsyncSession) -> None:
    """비회원 게시판 판정 절(대체 틀 메뉴·sitemap·틀 묶음이 함께 씀, 코드 검토 v1 N-2) ↔ can(GUEST)"""
    from app.models import Board as BoardModel
    from app.permissions import guest_listable_boards_clause, guest_readable_boards_clause

    author = await make_member(db)
    cases = {}
    for active in (True, False):
        for list_level in (0, 1):
            for read_level in (0, 1):
                board = await make_board(db, is_active=active, list_level=list_level, read_level=read_level)
                cases[board.id] = (board, await make_post(db, board, author))
    ids = list(cases)
    listable = set((await db.execute(select(BoardModel.id).where(BoardModel.id.in_(ids), guest_listable_boards_clause()))).scalars())
    readable = set((await db.execute(select(BoardModel.id).where(BoardModel.id.in_(ids), guest_readable_boards_clause()))).scalars())
    assert listable == {i for i, (b, _) in cases.items() if can(GUEST, NO_ROLE, "board.list", b)}
    assert readable == {i for i, (b, p) in cases.items() if can(GUEST, NO_ROLE, "post.read", b, p)}
    assert len(listable) == 2 and len(readable) == 1  # 대조: 조건 하나라도 다르면 위 두 줄이 갈린다


async def test_recent_comments_stay_in_their_board(db: AsyncSession) -> None:
    """게시판마다 따로 — 두 게시판·두 블록에서 댓글이 다른 게시판 블록으로 새지 않는다(LATERAL 상관이 풀리면 실패)"""
    author = await make_member(db)
    a = await make_board(db, slug="a")
    b = await make_board(db, slug="b")
    for board, label in ((a, "가"), (b, "나")):
        post = await make_post(db, board, author, title=f"{label} 글")
        db.add(Comment(post_id=post.id, member_id=author.id, author_name_snapshot="작성자", content=f"{label} 댓글"))
    await db.flush()
    lid = await _layout(db)
    await _block(db, lid, "aside", "recent_comments", {"board_ids": [a.id]})
    await _block(db, lid, "aside", "recent_comments", {"board_ids": [b.id]}, order=1)
    first, second = _flat(await frame_bundle(db))
    assert [(i["excerpt"], i["href"].split("/")[2]) for i in first["data"]["items"]] == [("가 댓글", "a")]
    assert [(i["excerpt"], i["href"].split("/")[2]) for i in second["data"]["items"]] == [("나 댓글", "b")]
