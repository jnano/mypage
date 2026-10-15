"""댓글(§4.4, §8.6) — 1단 답글, 스레드 순서·커서, 권한, 개수, 소프트 삭제, 블라인드, 멱등, 묶음 응답."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.comments import queries as comment_queries
from app.models import BoardModerator, Comment, MemberSanction, OutboxEvent, PostStat
from tests.factories import make_board, make_member, make_post
from tests.helpers import as_member, count_queries

pytestmark = pytest.mark.anyio


async def _setup(db: AsyncSession, **board_kw):
    author = await make_member(db, level=1, display_name="글쓴이")
    alice = await make_member(db, level=1, display_name="가람")
    bob = await make_member(db, level=1, display_name="나래")
    board = await make_board(db, slug="free", **board_kw)
    post = await make_post(db, board, author)
    db.add(PostStat(post_id=post.id))
    await db.commit()
    return author, alice, bob, board, post


async def _write(client: AsyncClient, post_id: int, member_id: int, content: str, reply_to: int | None = None, **headers):
    body = {"content": content} | ({"reply_to": reply_to} if reply_to else {})
    return await client.post(f"/api/posts/{post_id}/comments", json=body, headers=as_member(member_id) | headers)


async def _page(client: AsyncClient, post_id: int, member_id: int | None = None) -> dict:
    headers = as_member(member_id) if member_id else {}
    res = await client.get(f"/api/posts/{post_id}/page", headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


async def test_threads_and_one_level_replies(dev_header, committed_db, client) -> None:
    _, alice, bob, _, post = await _setup(committed_db)
    first = (await _write(client, post.id, alice.id, "첫 댓글")).json()["comment"]["id"]
    second = (await _write(client, post.id, bob.id, "두 번째")).json()["comment"]["id"]
    reply = (await _write(client, post.id, bob.id, "답글", reply_to=first)).json()["comment"]
    nested = (await _write(client, post.id, alice.id, "답글의 답글", reply_to=reply["id"])).json()["comment"]
    assert reply["parent_id"] == first and nested["parent_id"] == first  # 1단으로 평평하게

    items = (await _page(client, post.id))["comments"]["items"]
    assert [c["id"] for c in items] == [first, reply["id"], nested["id"], second]  # 스레드 순서
    by_id = {c["id"]: c for c in items}
    assert by_id[nested["id"]]["reply_to"] == {"id": reply["id"], "author_name": "나래"}  # 실제로 답한 상대
    assert by_id[reply["id"]]["reply_to"] is None  # 부모에게 답한 것은 따로 표시하지 않는다
    assert by_id[first]["author_id"] == alice.id and by_id[first]["content"] == "첫 댓글"
    assert (await _page(client, post.id))["post"]["stats"]["comments"] == 4


async def test_cursor_paging(committed_db, client, monkeypatch) -> None:
    monkeypatch.setattr(comment_queries, "PAGE_SIZE", 2)
    _, alice, _, _, post = await _setup(committed_db)
    roots = []
    for i in range(3):
        c = Comment(post_id=post.id, member_id=alice.id, author_name_snapshot="가람", content=f"c{i}")
        committed_db.add(c)
        await committed_db.flush()
        roots.append(c.id)
    committed_db.add(Comment(post_id=post.id, member_id=alice.id, author_name_snapshot="가람", content="r", parent_id=roots[0]))
    await committed_db.commit()

    first = (await _page(client, post.id))["comments"]
    assert len(first["items"]) == 2 and first["next_cursor"]
    rest = (await client.get(f"/api/posts/{post.id}/comments", params={"cursor": first["next_cursor"]})).json()
    assert [c["content"] for c in first["items"] + rest["items"]] == ["c0", "r", "c1", "c2"]
    assert rest["next_cursor"] is None and rest["cache"]["tags"] == [f"post:{post.id}"]
    assert (await client.get(f"/api/posts/{post.id}/comments", params={"cursor": "x"})).status_code == 422


async def test_permissions(dev_header, committed_db, client) -> None:
    author, alice, _, board, post = await _setup(committed_db)
    closed = await make_board(committed_db, slug="closed", allow_comments=False)
    closed_post = await make_post(committed_db, closed, author)
    secret = await make_post(committed_db, board, author, is_secret=True)
    leveled = await make_board(committed_db, slug="leveled", comment_level=5)
    leveled_post = await make_post(committed_db, leveled, author)
    committed_db.add(MemberSanction(member_id=alice.id, scope_board_id=leveled.id, actions=["write"], reason="r"))
    await committed_db.commit()

    async def code(res):
        return res.status_code, res.json().get("code")

    assert await code(await client.post(f"/api/posts/{post.id}/comments", json={"content": "x"})) == (401, "login_required")
    assert await code(await _write(client, closed_post.id, alice.id, "x")) == (403, "comment_create_forbidden")
    assert await code(await _write(client, leveled_post.id, alice.id, "x")) == (403, "comment_create_forbidden")
    assert await code(await _write(client, secret.id, alice.id, "x")) == (404, "post_not_found")  # 볼 수 없는 글은 존재도 숨김
    assert await code(await _write(client, secret.id, author.id, "x")) == (201, None)  # 작성자는 자기 비밀글에
    assert await code(await _write(client, 99_999, alice.id, "x")) == (404, "post_not_found")
    assert await code(await _write(client, post.id, alice.id, "   ")) == (422, "validation_error")
    # 다른 글의 댓글에 답할 수 없다
    other = (await _write(client, secret.id, author.id, "다른 글")).json()["comment"]["id"]
    assert await code(await _write(client, post.id, alice.id, "x", reply_to=other)) == (422, "validation_error")


async def test_comment_ban_blocks_create_and_update_but_not_delete(dev_header, committed_db, client) -> None:
    _, alice, _, board, post = await _setup(committed_db)
    mine = (await _write(client, post.id, alice.id, "내 댓글")).json()["comment"]["id"]
    committed_db.add(MemberSanction(member_id=alice.id, scope_board_id=board.id, actions=["comment"], reason="r"))
    await committed_db.commit()
    assert (await _write(client, post.id, alice.id, "또")).status_code == 403
    assert (await client.patch(f"/api/comments/{mine}", json={"content": "고침"}, headers=as_member(alice.id))).status_code == 403
    assert (await client.delete(f"/api/comments/{mine}", headers=as_member(alice.id))).status_code == 200


async def test_edit_and_delete(dev_header, committed_db, client) -> None:
    _, alice, bob, board, post = await _setup(committed_db)
    root = (await _write(client, post.id, alice.id, "원댓글")).json()["comment"]["id"]
    reply = (await _write(client, post.id, bob.id, "답글", reply_to=root)).json()["comment"]["id"]
    lone = (await _write(client, post.id, bob.id, "혼자")).json()["comment"]["id"]

    assert (await client.patch(f"/api/comments/{root}", json={"content": "고침"}, headers=as_member(bob.id))).status_code == 403
    res = await client.patch(f"/api/comments/{root}", json={"content": "고친 원댓글"}, headers=as_member(alice.id))
    assert res.status_code == 200 and res.json()["invalidate"]["now"] == [f"post:{post.id}", "recent:comments"]

    assert (await client.delete(f"/api/comments/{root}", headers=as_member(alice.id))).status_code == 200
    assert (await client.delete(f"/api/comments/{lone}", headers=as_member(bob.id))).status_code == 200
    assert (await client.delete(f"/api/comments/{lone}", headers=as_member(bob.id))).status_code == 404  # 이미 지움

    page = await _page(client, post.id)
    items = {c["id"]: c for c in page["comments"]["items"]}
    assert set(items) == {root, reply}  # 답글이 있는 원댓글만 자리를 남기고, 혼자인 댓글은 사라진다
    assert items[root]["masked"] == "deleted"
    assert items[root]["content"] is None and items[root]["author_name"] is None
    assert page["post"]["stats"]["comments"] == 1
    stored = (await committed_db.execute(select(Comment.content).where(Comment.id == root))).scalar_one()
    assert stored == ""  # 지운 내용은 남기지 않는다


async def test_blinded_comment_masked_except_for_moderator(dev_header, committed_db, client) -> None:
    _, alice, bob, board, post = await _setup(committed_db)
    cid = (await _write(client, post.id, alice.id, "가릴 댓글")).json()["comment"]["id"]
    await committed_db.execute(update(Comment).where(Comment.id == cid).values(is_blinded=True, blind_source="manual"))
    committed_db.add(BoardModerator(board_id=board.id, member_id=bob.id))
    await committed_db.commit()
    guest = (await _page(client, post.id))["comments"]["items"][0]
    assert (guest["content"], guest["masked"]) == (None, "blinded")
    mod = (await _page(client, post.id, bob.id))["comments"]["items"][0]
    assert (mod["content"], mod["masked"], mod["is_blinded"]) == ("가릴 댓글", None, True)


async def test_idempotency_and_side_effects(dev_header, committed_db, client) -> None:
    _, alice, _, _, post = await _setup(committed_db)
    a = await _write(client, post.id, alice.id, "한 번만", **{"Idempotency-Key": "c-1"})
    b = await _write(client, post.id, alice.id, "한 번만", **{"Idempotency-Key": "c-1"})
    assert a.json() == b.json() and b.headers["idempotency-replayed"] == "true"
    assert a.json()["invalidate"] == {"now": [f"post:{post.id}", "recent:comments"], "max": []}
    events = (await committed_db.execute(select(OutboxEvent.type, OutboxEvent.payload))).all()
    assert [(e.type, e.payload["comment_id"]) for e in events] == [("comment.created", a.json()["comment"]["id"])]
    assert (await committed_db.execute(select(PostStat.comment_count))).scalar_one() == 1


async def test_post_page_query_budget_with_comments(dev_header, committed_db, client) -> None:
    _, alice, bob, _, post = await _setup(committed_db)
    for i in range(30):
        await _write(client, post.id, alice.id if i % 2 else bob.id, f"댓글 {i}")
    with count_queries() as q:
        await _page(client, post.id, alice.id)
    assert q["n"] <= 8, q["sql"]  # 댓글 수와 무관하게 한 번에(N+1 없음)
