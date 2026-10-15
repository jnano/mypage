"""글 화면 묶음 응답 GET /api/posts/{id}/page — §3.6, §5.3, §10(410)."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PostRelation, PostTombstone
from tests.factories import make_board, make_member, make_post
from tests.helpers import as_member, count_queries

pytestmark = pytest.mark.anyio
NOW = datetime.now(UTC)


async def test_view_with_neighbors_and_related(committed_db: AsyncSession, client: AsyncClient) -> None:
    db = committed_db
    board = await make_board(db, slug="free")
    members_board = await make_board(db, slug="members", list_level=2)
    old = await make_post(db, board, None, title="이전 글", published_at=NOW - timedelta(hours=2))
    secret_next = await make_post(db, board, None, title="비밀", is_secret=True, published_at=NOW)
    post = await make_post(db, board, None, title="회의 안내", published_at=NOW - timedelta(hours=1))
    hidden_related = await make_post(db, members_board, None, title="회원 글")
    db.add_all(
        [
            PostRelation(source_post_id=post.id, target_post_id=old.id),
            PostRelation(source_post_id=post.id, target_post_id=hidden_related.id),
        ]
    )
    await db.commit()

    res = await client.get(f"/api/posts/{post.id}/page")
    assert res.status_code == 200
    body = res.json()
    assert body["post"]["title"] == "회의 안내" and body["post"]["indexable"] is True
    assert body["board"]["slug"] == "free"
    assert body["neighbors"]["prev"] == {"id": old.id, "title": "이전 글"}
    assert body["neighbors"]["next"] == {"id": secret_next.id, "title": None}  # 비밀글 제목은 가림
    assert [r["id"] for r in body["related"]] == [old.id]  # 열 수 없는 관련 글은 빠진다
    assert body["attachments"] == []
    assert body["cache"]["tags"] == [f"post:{post.id}", "board:free"]


async def test_denials(dev_header, committed_db: AsyncSession, client: AsyncClient) -> None:
    db = committed_db
    author = await make_member(db)
    board = await make_board(db, slug="free")
    secret = await make_post(db, board, author, is_secret=True)
    blinded = await make_post(db, board, author, is_blinded=True, blind_source="manual")
    leveled = await make_post(db, board, author, min_view_level=5)
    draft = await make_post(db, board, author, status="draft")
    db.add(PostTombstone(post_id=987654, board_slug="free"))
    await db.commit()

    async def code(post_id: int, headers=None):
        res = await client.get(f"/api/posts/{post_id}/page", headers=headers or {})
        return res.status_code, res.json().get("code")

    assert await code(secret.id) == (403, "post_secret")
    assert await code(blinded.id) == (403, "post_blinded")
    assert await code(leveled.id) == (403, "post_level")
    assert await code(draft.id) == (404, "post_not_found")  # 존재를 드러내지 않는다
    assert await code(987654) == (410, "post_gone")
    assert await code(123456789) == (404, "post_not_found")
    # 작성자는 비밀글·임시 글을 본다
    assert (await client.get(f"/api/posts/{secret.id}/page", headers=as_member(author.id))).status_code == 200
    draft_res = await client.get(f"/api/posts/{draft.id}/page", headers=as_member(author.id))
    assert draft_res.status_code == 200 and draft_res.json()["neighbors"] == {"prev": None, "next": None}


async def test_private_post_is_not_indexable(dev_header, committed_db: AsyncSession, client: AsyncClient) -> None:
    author = await make_member(committed_db)
    board = await make_board(committed_db, slug="free")
    secret = await make_post(committed_db, board, author, is_secret=True)
    await committed_db.commit()
    body = (await client.get(f"/api/posts/{secret.id}/page", headers=as_member(author.id))).json()
    assert body["post"]["indexable"] is False


@pytest.mark.parametrize("who", ["guest", "member"])
async def test_query_budget(dev_header, committed_db: AsyncSession, client: AsyncClient, who: str) -> None:
    member = await make_member(committed_db)
    board = await make_board(committed_db, slug="free")
    post = await make_post(committed_db, board, member)
    await committed_db.commit()
    headers = as_member(member.id) if who == "member" else {}
    with count_queries() as q:
        res = await client.get(f"/api/posts/{post.id}/page", headers=headers)
    assert res.status_code == 200
    assert q["n"] <= 8, q["sql"]
