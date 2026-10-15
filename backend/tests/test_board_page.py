"""게시판 화면 묶음 응답 GET /api/boards/{slug}/page — §3.6, §5.2, §15(쿼리 수)."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BoardCategory, BoardModerator, BoardSlugHistory, PostCategory
from tests.factories import make_board, make_member, make_post
from tests.helpers import as_member, count_queries

pytestmark = pytest.mark.anyio
NOW = datetime.now(UTC)


async def _seed(db: AsyncSession, **board_kw):
    author = await make_member(db, level=1)
    other = await make_member(db, level=1)
    board = await make_board(db, slug="free", **board_kw)
    cat = BoardCategory(board_id=board.id, name="회의")
    db.add(cat)
    await db.flush()
    posts = {
        "plain": await make_post(db, board, author, title="회의 안내"),
        "secret": await make_post(db, board, author, title="비공개 문의", is_secret=True),
        "blinded": await make_post(db, board, author, title="가려진 글", is_blinded=True, blind_source="manual"),
        "pinned": await make_post(db, board, author, title="고정 글", is_pinned=True, pin_order=1),
        "expired": await make_post(db, board, author, title="지난 모집", expires_at=NOW - timedelta(days=1)),
        "draft": await make_post(db, board, author, title="임시 글", status="draft"),
    }
    db.add(PostCategory(post_id=posts["plain"].id, category_id=cat.id))
    await db.commit()
    return board, author, other, cat, posts


async def test_guest_list_masks_and_strips(committed_db: AsyncSession, client: AsyncClient) -> None:
    _, _, _, _, posts = await _seed(committed_db)
    res = await client.get("/api/boards/free/page")
    assert res.status_code == 200
    body = res.json()
    rows = {r["id"]: r for r in body["posts"]}
    # 일반 목록: 고정·만료·임시 글 제외, 비밀·블라인드는 제목 가림(mask 기본)
    assert set(rows) == {posts["plain"].id, posts["secret"].id, posts["blinded"].id}
    assert rows[posts["plain"].id]["title"] == "회의 안내"
    assert (rows[posts["secret"].id]["title"], rows[posts["secret"].id]["masked"]) == (None, "secret")
    assert (rows[posts["blinded"].id]["title"], rows[posts["blinded"].id]["masked"]) == (None, "blinded")
    assert [p["id"] for p in body["pinned"]] == [posts["pinned"].id]
    assert body["page"]["total"] == 3 and body["cache"]["tags"] == ["board:free"]
    assert body["categories"][0]["name"] == "회의"
    # 최신순
    assert [r["id"] for r in body["posts"]] == sorted(rows, reverse=True)


async def test_author_sees_own_secret_title(dev_header, committed_db: AsyncSession, client: AsyncClient) -> None:
    _, author, other, _, posts = await _seed(committed_db)
    mine = {r["id"]: r for r in (await client.get("/api/boards/free/page", headers=as_member(author.id))).json()["posts"]}
    theirs = {r["id"]: r for r in (await client.get("/api/boards/free/page", headers=as_member(other.id))).json()["posts"]}
    assert mine[posts["secret"].id]["title"] == "비공개 문의"
    assert theirs[posts["secret"].id]["title"] is None


async def test_hide_board_removes_masked_rows_and_counts(committed_db: AsyncSession, client: AsyncClient) -> None:
    _, _, _, _, posts = await _seed(committed_db, hidden_post_listing="hide")
    body = (await client.get("/api/boards/free/page")).json()
    assert [r["id"] for r in body["posts"]] == [posts["plain"].id]
    assert body["page"]["total"] == 1


async def test_moderator_sees_titles(dev_header, committed_db: AsyncSession, client: AsyncClient) -> None:
    board, _, other, _, posts = await _seed(committed_db, hidden_post_listing="hide")
    committed_db.add(BoardModerator(board_id=board.id, member_id=other.id))
    await committed_db.commit()
    rows = {r["id"]: r for r in (await client.get("/api/boards/free/page", headers=as_member(other.id))).json()["posts"]}
    assert rows[posts["blinded"].id]["title"] == "가려진 글"


async def test_category_and_archived(committed_db: AsyncSession, client: AsyncClient) -> None:
    _, _, _, cat, posts = await _seed(committed_db)
    by_cat = (await client.get(f"/api/boards/free/page?category={cat.id}")).json()
    assert [r["id"] for r in by_cat["posts"]] == [posts["plain"].id]
    archived = (await client.get("/api/boards/free/page?archived=true")).json()
    assert [r["id"] for r in archived["posts"]] == [posts["expired"].id]
    assert archived["posts"][0]["expired"] is True and archived["pinned"] == []
    assert (await client.get("/api/boards/free/page?category=999999")).status_code == 404


async def test_access_errors(committed_db: AsyncSession, client: AsyncClient) -> None:
    await make_board(committed_db, slug="members", list_level=2)
    await make_board(committed_db, slug="closed", is_active=False)
    moved = await make_board(committed_db, slug="renamed")
    committed_db.add(BoardSlugHistory(old_slug="old-name", board_id=moved.id))
    await committed_db.commit()

    res = await client.get("/api/boards/members/page")
    assert (res.status_code, res.json()["code"]) == (403, "board_forbidden")
    assert res.headers["content-type"] == "application/problem+json"
    assert (await client.get("/api/boards/closed/page")).status_code == 404
    assert (await client.get("/api/boards/nothing/page")).status_code == 404
    res = await client.get("/api/boards/old-name/page?page=2")
    assert (res.status_code, res.headers["location"]) == (308, "/api/boards/renamed/page?page=2")
    res = await client.get("/api/boards/renamed/page?page=501")
    assert (res.status_code, res.json()["code"]) == (400, "page_out_of_range")
    assert (await client.get("/api/boards/renamed/page?sort=views")).status_code == 422


async def test_pagination(committed_db: AsyncSession, client: AsyncClient) -> None:
    board = await make_board(committed_db, slug="free", posts_per_page=5)
    for i in range(12):
        await make_post(committed_db, board, None, title=f"글 {i}", published_at=NOW - timedelta(minutes=i))
    await committed_db.commit()
    page3 = (await client.get("/api/boards/free/page?page=3")).json()
    assert [r["title"] for r in page3["posts"]] == ["글 10", "글 11"]
    assert page3["page"]["last_page"] == 3


@pytest.mark.parametrize("who", ["guest", "member"])
async def test_query_budget(dev_header, committed_db: AsyncSession, client: AsyncClient, who: str) -> None:
    # §15.1 화면 하나당 DB 쿼리 ≤ 8(권한 준비 포함). 글이 많아도 늘지 않아야 한다(N+1 없음)
    _, author, *_ = await _seed(committed_db)
    headers = as_member(author.id) if who == "member" else {}
    with count_queries() as q:
        res = await client.get("/api/boards/free/page", headers=headers)
    assert res.status_code == 200
    assert q["n"] <= 8, q["sql"]
