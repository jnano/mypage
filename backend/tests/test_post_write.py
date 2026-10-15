"""글 작성·수정 — §3.1-4 쓰기 순서, §5.4 칸 권한, §6 멱등·요청 수 제한, 낙관적 잠금."""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import rate_limit
from app.models import (
    Board,
    BoardCategory,
    MemberSanction,
    OutboxEvent,
    Post,
    PostCategory,
    PostSearch,
    PostStat,
)
from tests.factories import make_board, make_member
from tests.helpers import as_member

pytestmark = pytest.mark.anyio

BODY = {"title": "회의 안내", "content": "# 일정\n\n**목요일** 오후 7시"}


async def _setup(db: AsyncSession, **board_kw):
    member = await make_member(db, level=1, display_name="회원A")
    board = await make_board(db, slug="free", editor="markdown", allow_secret=True, **board_kw)
    cat = BoardCategory(board_id=board.id, name="회의")
    db.add(cat)
    await db.commit()
    return member, board, cat


async def _create(client: AsyncClient, member_id: int, body=None, slug="free", **headers):
    return await client.post(
        f"/api/boards/{slug}/posts", json=body or BODY, headers=as_member(member_id) | headers
    )


async def test_create_writes_all_rows_in_one_commit(dev_header, committed_db, client) -> None:
    member, board, cat = await _setup(committed_db)
    res = await _create(client, member.id, BODY | {"category_ids": [cat.id], "is_secret": False})
    assert res.status_code == 201, res.text
    data = res.json()
    post_id = data["post"]["id"]
    assert res.headers["location"] == f"/api/posts/{post_id}" and res.headers["etag"] == '"1"'
    assert data["post"]["path"] == f"/boards/free/{post_id}"
    assert data["invalidate"] == {
        "now": [f"post:{post_id}", "board:free", "recent:posts"],
        "max": ["boards:activity", "sitemap", "feed:free"],
    }

    db = committed_db
    post = (await db.execute(select(Post).where(Post.id == post_id))).scalar_one()
    assert (post.content_format, post.content_source) == ("markdown", BODY["content"])
    assert post.content_html == "<h2>일정</h2>\n<p><strong>목요일</strong> 오후 7시</p>\n"
    assert post.author_name_snapshot == "회원A" and post.status == "published" and post.published_at
    assert (await db.execute(select(PostStat.view_count).where(PostStat.post_id == post_id))).scalar_one() == 0
    search = (await db.execute(select(PostSearch).where(PostSearch.post_id == post_id))).scalar_one()
    assert (search.post_open, search.title_compact, search.content_compact) == (True, "회의안내", "일정목요일오후7시")
    assert (await db.execute(select(PostCategory.category_id).where(PostCategory.post_id == post_id))).scalars().all() == [cat.id]
    events = (await db.execute(select(OutboxEvent.type, OutboxEvent.payload))).all()
    assert [(e.type, e.payload["post_id"]) for e in events] == [("post.created", post_id)]


async def test_secret_post_is_not_open_for_search(dev_header, committed_db, client) -> None:
    member, *_ = await _setup(committed_db)
    post_id = (await _create(client, member.id, BODY | {"is_secret": True})).json()["post"]["id"]
    open_ = (await committed_db.execute(select(PostSearch.post_open).where(PostSearch.post_id == post_id))).scalar_one()
    assert open_ is False


async def test_create_rejections(dev_header, committed_db, client) -> None:
    member, board, cat = await _setup(committed_db)
    other_board = await make_board(committed_db, slug="other")
    other_cat = BoardCategory(board_id=other_board.id, name="다른")
    committed_db.add(other_cat)
    await make_board(committed_db, slug="notice", write_level=9)
    await make_board(committed_db, slug="plain", allow_secret=False)
    await committed_db.commit()

    async def code(res):
        return res.status_code, res.json().get("code")

    assert await code(await client.post("/api/boards/free/posts", json=BODY)) == (401, "login_required")
    assert await code(await _create(client, member.id, slug="notice")) == (403, "post_create_forbidden")
    assert await code(await _create(client, member.id, slug="nothing")) == (404, "board_not_found")
    assert await code(await _create(client, member.id, BODY | {"is_secret": True}, slug="plain")) == (422, "validation_error")
    assert await code(await _create(client, member.id, BODY | {"category_ids": [other_cat.id]})) == (422, "validation_error")
    assert await code(await _create(client, member.id, BODY | {"title": "  "})) == (422, "validation_error")
    assert await code(await _create(client, member.id, BODY | {"is_pinned": True})) == (422, "validation_error")
    bad_image = await _create(client, member.id, BODY | {"content": "![x](https://e.com/a.png)"})
    assert bad_image.json()["errors"][0]["field"] == "content"
    # 거부된 요청은 아무 글도 남기지 않는다
    assert (await committed_db.execute(select(Post.id))).all() == []


async def test_sanction_blocks_create(dev_header, committed_db, client) -> None:
    member, board, _ = await _setup(committed_db)
    committed_db.add(MemberSanction(member_id=member.id, scope_board_id=board.id, actions=["write"], reason="r"))
    await committed_db.commit()
    assert (await _create(client, member.id)).status_code == 403


async def test_idempotency(dev_header, committed_db, client) -> None:
    member, *_ = await _setup(committed_db)
    first = await _create(client, member.id, **{"Idempotency-Key": "k-1"})
    again = await _create(client, member.id, **{"Idempotency-Key": "k-1"})
    assert again.status_code == 201 and again.json() == first.json()
    assert again.headers["idempotency-replayed"] == "true"
    reused = await _create(client, member.id, BODY | {"title": "다른 글"}, **{"Idempotency-Key": "k-1"})
    assert (reused.status_code, reused.json()["code"]) == (422, "idempotency_key_reused")
    assert len((await committed_db.execute(select(Post.id))).all()) == 1


async def test_failed_request_releases_idempotency_key(dev_header, committed_db, client) -> None:
    member, *_ = await _setup(committed_db)
    bad = await _create(client, member.id, BODY | {"content": "![x](https://e.com/a.png)"}, **{"Idempotency-Key": "k-2"})
    assert bad.status_code == 422
    ok = await _create(client, member.id, BODY | {"content": "![x](https://e.com/a.png)"}, **{"Idempotency-Key": "k-2"})
    assert ok.status_code == 422  # 같은 키로 다시 시도할 수 있다(409 '처리 중'이 아니다)


async def test_rate_limit(dev_header, committed_db, client, monkeypatch) -> None:
    member, *_ = await _setup(committed_db)
    # 창을 하루로 — 테스트 중에 창 경계를 넘지 않게
    monkeypatch.setitem(rate_limit.LIMITS, "post.create", rate_limit.Limit(2, 86400))
    responses = [await _create(client, member.id) for _ in range(3)]
    assert [r.status_code for r in responses] == [201, 201, 429]
    assert responses[2].json()["code"] == "rate_limited"
    assert int(responses[2].headers["retry-after"]) >= 1


# ── 수정 ─────────────────────────────────────────────────


async def _created(client, member_id) -> int:
    return (await _create(client, member_id)).json()["post"]["id"]


async def test_update_with_if_match(dev_header, committed_db, client) -> None:
    member, board, cat = await _setup(committed_db)
    post_id = await _created(client, member.id)
    headers = as_member(member.id)

    res = await client.patch(f"/api/posts/{post_id}", json={"title": "고친 제목", "category_ids": [cat.id]}, headers=headers | {"If-Match": '"1"'})
    assert res.status_code == 200 and res.json()["post"]["version"] == 2 and res.headers["etag"] == '"2"'
    stale = await client.patch(f"/api/posts/{post_id}", json={"title": "또"}, headers=headers | {"If-Match": '"1"'})
    assert (stale.status_code, stale.json()["code"], stale.headers["etag"]) == (412, "version_mismatch", '"2"')
    missing = await client.patch(f"/api/posts/{post_id}", json={"title": "또"}, headers=headers)
    assert missing.status_code == 428

    db = committed_db
    post = (await db.execute(select(Post).where(Post.id == post_id))).scalar_one()
    assert (post.title, post.version) == ("고친 제목", 2) and post.content_updated_at is not None
    search = (await db.execute(select(PostSearch.title_compact).where(PostSearch.post_id == post_id))).scalar_one()
    assert search == "고친제목"


async def test_update_keeps_written_format(dev_header, committed_db, client) -> None:
    # 게시판 에디터를 바꿔도 이미 쓴 글은 쓴 형식(마크다운)으로 수정한다(§8.4)
    member, board, _ = await _setup(committed_db)
    post_id = await _created(client, member.id)
    await committed_db.execute(update(Board).where(Board.id == board.id).values(editor="rich"))
    await committed_db.commit()
    res = await client.patch(f"/api/posts/{post_id}", json={"content": "**굵게**"}, headers=as_member(member.id) | {"If-Match": '"1"'})
    assert res.status_code == 200
    edit = (await client.get(f"/api/posts/{post_id}", headers=as_member(member.id))).json()
    assert (edit["content_format"], edit["content"], edit["version"]) == ("markdown", "**굵게**", 2)


async def test_update_permissions(dev_header, committed_db, client) -> None:
    member, *_ = await _setup(committed_db)
    other = await make_member(committed_db)
    await committed_db.commit()
    post_id = await _created(client, member.id)
    res = await client.patch(f"/api/posts/{post_id}", json={"title": "x"}, headers=as_member(other.id) | {"If-Match": '"1"'})
    assert res.status_code == 403
    assert (await client.get(f"/api/posts/{post_id}", headers=as_member(other.id))).status_code == 403
    # 관리용 칸(§5.4 post.moderate)은 작성자가 바꿀 수 없다, 표에 없는 칸은 422
    res = await client.patch(f"/api/posts/{post_id}", json={"is_pinned": True}, headers=as_member(member.id) | {"If-Match": '"1"'})
    assert res.status_code == 403
    res = await client.patch(f"/api/posts/{post_id}", json={"status": "draft"}, headers=as_member(member.id) | {"If-Match": '"1"'})
    assert res.status_code == 422
    res = await client.patch(f"/api/posts/{post_id}", json={}, headers=as_member(member.id) | {"If-Match": '"1"'})
    assert res.status_code == 422


async def test_trashed_post_is_not_editable(dev_header, committed_db, client) -> None:
    member, *_ = await _setup(committed_db)
    post_id = await _created(client, member.id)
    await committed_db.execute(
        update(Post).where(Post.id == post_id).values(status="trashed", trashed_at=datetime.now(UTC), trashed_from_status="published")
    )
    await committed_db.commit()
    res = await client.patch(f"/api/posts/{post_id}", json={"title": "x"}, headers=as_member(member.id) | {"If-Match": '"1"'})
    assert (res.status_code, res.json()["code"]) == (409, "post_not_editable")


async def test_preview(dev_header, committed_db, client) -> None:
    member, *_ = await _setup(committed_db)
    res = await client.post("/api/editor/preview", json={"markdown": "https://youtu.be/dQw4w9WgXcQ"}, headers=as_member(member.id))
    assert res.status_code == 200 and "youtube-nocookie.com/embed/dQw4w9WgXcQ" in res.json()["html"]
    assert (await client.post("/api/editor/preview", json={"markdown": "x"})).status_code == 401
