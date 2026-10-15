"""개인 조각 GET /api/me/page-state(§3.3·§3.6)와 has_restricted_posts."""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BoardModerator, Notification
from tests.factories import make_board, make_member, make_post
from tests.helpers import as_member, count_queries

pytestmark = pytest.mark.anyio


async def _seed(db: AsyncSession):
    author = await make_member(db, level=1)
    other = await make_member(db, level=1)
    mod = await make_member(db, level=1)
    board = await make_board(db, slug="free")
    elsewhere = await make_board(db, slug="other")
    db.add(BoardModerator(board_id=board.id, member_id=mod.id))
    posts = {
        "plain": await make_post(db, board, author),
        "secret": await make_post(db, board, author, title="내 비밀", is_secret=True),
        "others_secret": await make_post(db, board, other, title="남의 비밀", is_secret=True),
        "blinded": await make_post(db, board, author, title="가림", is_blinded=True, blind_source="manual"),
        "foreign": await make_post(db, elsewhere, author, is_secret=True),
    }
    await db.commit()
    return author, other, mod, posts


def _ids(posts) -> str:
    return ",".join(str(p.id) for p in posts.values())


async def test_guest_gets_empty_state(committed_db, client: AsyncClient) -> None:
    _, _, _, posts = await _seed(committed_db)
    res = await client.get(f"/api/me/page-state?board=free&ids={_ids(posts)}")
    assert res.status_code == 200 and res.headers["cache-control"] == "no-store"
    assert res.json() == {
        "viewer": None, "board_role": {"is_moderator": False}, "unmasked": [], "editable": [],
        "unread_notifications": 0, "unread_capped": False,
    }  # fmt: skip


async def test_author_unmasks_own_secret_only(dev_header, committed_db, client: AsyncClient) -> None:
    author, _, _, posts = await _seed(committed_db)
    body = (await client.get(f"/api/me/page-state?board=free&ids={_ids(posts)}", headers=as_member(author.id))).json()
    assert body["unmasked"] == [{"id": posts["secret"].id, "title": "내 비밀"}]  # 블라인드는 작성자도 못 푼다
    # 다른 게시판 글은 이 게시판 화면의 대상이 아니다
    assert sorted(body["editable"]) == sorted([posts["plain"].id, posts["secret"].id, posts["blinded"].id])
    assert body["board_role"] == {"is_moderator": False}


async def test_moderator_unmasks_everything_on_board(dev_header, committed_db, client: AsyncClient) -> None:
    _, _, mod, posts = await _seed(committed_db)
    body = (await client.get(f"/api/me/page-state?board=free&ids={_ids(posts)}", headers=as_member(mod.id))).json()
    assert {u["id"] for u in body["unmasked"]} == {posts["secret"].id, posts["others_secret"].id, posts["blinded"].id}
    assert body["board_role"] == {"is_moderator": True}


async def test_unread_notifications_capped(dev_header, committed_db, client: AsyncClient) -> None:
    author, *_ = await _seed(committed_db)
    committed_db.add_all(
        [
            Notification(recipient_id=author.id, type="comment.on_my_post", title_snapshot="t",
                         group_key=f"g{i}", dedupe_key=f"d{i}", read_at=datetime.now(UTC) if i < 5 else None)  # fmt: skip
            for i in range(105)
        ]
    )
    await committed_db.commit()
    body = (await client.get("/api/me/page-state?board=free", headers=as_member(author.id))).json()
    assert (body["unread_notifications"], body["unread_capped"]) == (100, True)


async def test_bad_ids(dev_header, committed_db, client: AsyncClient) -> None:
    author, *_ = await _seed(committed_db)
    h = as_member(author.id)
    assert (await client.get("/api/me/page-state?board=free&ids=a,b", headers=h)).status_code == 422
    many = ",".join(str(i) for i in range(1, 102))
    assert (await client.get(f"/api/me/page-state?board=free&ids={many}", headers=h)).status_code == 422
    assert (await client.get("/api/me/page-state?board=nothing&ids=1", headers=h)).status_code == 404


async def test_query_budget(dev_header, committed_db, client: AsyncClient) -> None:
    author, _, _, posts = await _seed(committed_db)
    with count_queries() as q:
        res = await client.get(f"/api/me/page-state?board=free&ids={_ids(posts)}", headers=as_member(author.id))
    assert res.status_code == 200 and q["n"] <= 5, q["sql"]


async def test_has_restricted_posts_flag(committed_db, client: AsyncClient) -> None:
    board = await make_board(committed_db, slug="free")
    clean = await make_board(committed_db, slug="clean")
    await make_post(committed_db, board, None, is_secret=True)
    await make_post(committed_db, clean, None)
    await make_post(committed_db, clean, None, is_secret=True, status="draft")  # 공개 상태가 아니면 세지 않는다
    await committed_db.commit()
    assert (await client.get("/api/boards/free/page")).json()["cache"]["has_restricted_posts"] is True
    assert (await client.get("/api/boards/clean/page")).json()["cache"]["has_restricted_posts"] is False
