"""내 목록 — 설계도 §6.2. 본인 것만, 휴지통·지운 댓글 제외, 지금 읽을 수 없는 글은 제목 가림, 키셋 커서."""

from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.me import lists
from app.models import Comment, Post, PostScrap, PostStat
from tests.factories import make_board, make_member, make_post
from tests.helpers import as_member, count_queries

pytestmark = pytest.mark.anyio


async def _world(db: AsyncSession):
    me = await make_member(db, level=1, display_name="나")
    other = await make_member(db, level=1, display_name="남")
    board = await make_board(db, slug="free")
    return me, other, board


async def _all(client, path: str, member_id: int) -> list[dict]:
    """커서로 끝까지 넘긴 모든 항목"""
    items, cursor = [], None
    while True:
        url = path + (f"?cursor={quote(cursor)}" if cursor else "")
        body = (await client.get(url, headers=as_member(member_id))).json()
        items += body["items"]
        cursor = body["next_cursor"]
        if cursor is None:
            return items


async def test_my_posts_only_mine_without_trash(dev_header, committed_db, client) -> None:
    me, other, board = await _world(committed_db)
    extra = {"scheduled": {"published_at": datetime.now(UTC) + timedelta(days=1)}, "trashed": {"trashed_at": datetime.now(UTC)}}
    mine = {s: await make_post(committed_db, board, me, status=s, title=f"내 {s}", **extra.get(s, {})) for s in ("published", "draft", "pending", "scheduled", "trashed")}
    blinded = await make_post(committed_db, board, me, title="가려진 내 글", is_blinded=True)
    await make_post(committed_db, board, other, title="남의 글")
    committed_db.add(PostStat(post_id=mine["published"].id, comment_count=2, like_count=3))
    await committed_db.commit()
    res = await client.get("/api/me/posts", headers=as_member(me.id))
    assert res.status_code == 200 and res.headers["cache-control"] == "no-store"
    items = res.json()["items"]
    assert {i["id"] for i in items} == {mine[s].id for s in ("published", "draft", "pending", "scheduled")} | {blinded.id}
    by_id = {i["id"]: i for i in items}
    assert by_id[mine["draft"].id]["status"] == "draft"
    assert by_id[blinded.id]["is_blinded"] is True
    assert by_id[mine["published"].id]["stats"] == {"comments": 2, "likes": 3}
    assert by_id[mine["published"].id]["path"] == f"/boards/free/{mine['published'].id}"
    assert (await client.get("/api/me/posts")).status_code == 401


async def test_cursor_walks_every_row_once_including_ties(dev_header, committed_db, client, monkeypatch) -> None:
    me, _, board = await _world(committed_db)
    monkeypatch.setattr(lists, "PAGE_SIZE", 3)
    same = datetime(2026, 10, 1, tzinfo=UTC)
    ids = []
    for i in range(8):  # 같은 시각 넷 + 다른 시각 넷 — 같은 시각도 빠짐·겹침 없이
        p = await make_post(committed_db, board, me, title=f"글 {i}", created_at=same if i < 4 else same + timedelta(minutes=i))
        ids.append(p.id)
    await committed_db.commit()
    walked = [i["id"] for i in await _all(client, "/api/me/posts", me.id)]
    assert sorted(walked) == sorted(ids) and len(walked) == len(set(walked))
    assert (await client.get("/api/me/posts?cursor=nope", headers=as_member(me.id))).status_code == 422
    # 시간대 없는 시각은 받지 않는다(검토 묶음B N-3)
    assert (await client.get("/api/me/posts?cursor=2026-10-01T00:00:00|1", headers=as_member(me.id))).status_code == 422


async def test_my_comments_hide_unreadable_post_titles(dev_header, committed_db, client) -> None:
    me, other, board = await _world(committed_db)
    open_post = await make_post(committed_db, board, other, title="열린 글")
    closed = await make_post(committed_db, board, other, title="닫힐 글")
    rows = [
        Comment(post_id=open_post.id, member_id=me.id, author_name_snapshot="나", content="첫 댓글 " + "가" * 200),
        Comment(post_id=closed.id, member_id=me.id, author_name_snapshot="나", content="닫힌 글의 댓글"),
        Comment(post_id=open_post.id, member_id=me.id, author_name_snapshot="나", content="지운 댓글", status="deleted"),
        Comment(post_id=open_post.id, member_id=me.id, author_name_snapshot="나", content="가려진 댓글", is_blinded=True, blind_source="manual"),
        Comment(post_id=open_post.id, member_id=other.id, author_name_snapshot="남", content="남의 댓글"),
    ]
    committed_db.add_all(rows)
    await committed_db.commit()
    await committed_db.execute(update(Post).where(Post.id == closed.id).values(is_secret=True))  # post-clause: exempt — 시험
    await committed_db.commit()
    items = (await client.get("/api/me/comments", headers=as_member(me.id))).json()["items"]
    by_text = {i["excerpt"][:6]: i for i in items}
    assert set(by_text) == {"첫 댓글 가", "닫힌 글의 ", "가려진 댓글"}
    assert len(by_text["첫 댓글 가"]["excerpt"]) == lists.EXCERPT
    assert by_text["닫힌 글의 "]["post"] == {"id": closed.id, "title": None, "masked": "hidden"} and by_text["닫힌 글의 "]["path"] is None
    assert by_text["가려진 댓글"]["is_blinded"] is True
    assert by_text["첫 댓글 가"]["path"].startswith(f"/boards/free/{open_post.id}#c-")


async def test_my_scraps_mask_and_order(dev_header, committed_db, client) -> None:
    me, other, board = await _world(committed_db)
    a = await make_post(committed_db, board, other, title="먼저 스크랩")
    b = await make_post(committed_db, board, other, title="나중에 비공개")
    c = await make_post(committed_db, board, other, title="남이 스크랩")
    now = datetime.now(UTC)
    committed_db.add_all(
        [
            PostScrap(post_id=a.id, member_id=me.id, created_at=now - timedelta(hours=2)),
            PostScrap(post_id=b.id, member_id=me.id, created_at=now - timedelta(hours=1)),
            PostScrap(post_id=c.id, member_id=other.id),
        ]
    )
    await committed_db.commit()
    await committed_db.execute(update(Post).where(Post.id == b.id).values(status="trashed", trashed_at=datetime.now(UTC)))  # post-clause: exempt — 시험
    await committed_db.commit()
    items = (await client.get("/api/me/scraps", headers=as_member(me.id))).json()["items"]
    assert [i["post_id"] for i in items] == [b.id, a.id]  # 스크랩한 때 최신순
    assert items[0]["title"] is None and items[0]["masked"] == "hidden" and items[0]["path"] is None
    assert items[1]["title"] == "먼저 스크랩" and items[1]["board"] == {"slug": "free", "name": "자유게시판"}


@pytest.mark.parametrize("path", ["/api/me/posts", "/api/me/comments", "/api/me/scraps"])
async def test_query_budget(dev_header, committed_db, client, path) -> None:
    me, other, board = await _world(committed_db)
    for i in range(5):
        p = await make_post(committed_db, board, other if path != "/api/me/posts" else me, title=f"글 {i}")
        committed_db.add(PostScrap(post_id=p.id, member_id=me.id))
        committed_db.add(Comment(post_id=p.id, member_id=me.id, author_name_snapshot="나", content=f"댓글 {i}"))
    await committed_db.commit()
    with count_queries() as q:
        res = await client.get(path, headers=as_member(me.id))
    assert res.status_code == 200 and len(res.json()["items"]) == 5
    assert q["n"] <= 3, q["sql"]


async def test_my_post_links_follow_can_read(dev_header, committed_db, client) -> None:
    """작성자도 게시판 조건·가림·글 단위 등급을 통과해야 연다 — 링크는 can(post.read) 와 같은 판정(검토 v4.0.9 N-1)"""
    from app.auth.viewer import Viewer
    from app.models import Board
    from app.permissions import NO_ROLE, can

    me, _, board = await _world(committed_db)
    closed_board = await make_board(committed_db, slug="members", read_level=2)  # 회원 전용으로 바뀐 게시판
    posts = {
        "open": await make_post(committed_db, board, me, title="열림"),
        "draft": await make_post(committed_db, board, me, title="임시", status="draft"),
        "blinded": await make_post(committed_db, board, me, title="가려짐", is_blinded=True),
        "secret": await make_post(committed_db, board, me, title="내 비밀", is_secret=True),
        "level": await make_post(committed_db, board, me, title="등급", min_view_level=3),
        "board": await make_post(committed_db, closed_board, me, title="닫힌 게시판"),
    }
    await committed_db.commit()
    items = {i["id"]: i for i in (await client.get("/api/me/posts", headers=as_member(me.id))).json()["items"]}
    viewer = Viewer(member_id=me.id, level=1)
    for name, p in posts.items():
        b = (await committed_db.get(Board, p.board_id))
        expected = can(viewer, NO_ROLE, "post.read", b, p)
        assert (items[p.id]["path"] is not None) is expected, name
        assert items[p.id]["title"] == p.title  # 제목·배지는 늘 보인다
    assert {n for n, p in posts.items() if items[p.id]["path"] is None} == {"blinded", "level", "board"}
