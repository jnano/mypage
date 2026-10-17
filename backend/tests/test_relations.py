"""관련 글 편집 — 설계도 §6.2. 담당자·회원 작성자, 읽을 수 있는 공개 글, 최대 10(동시에도), 무효화·운영 기록."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BoardModerator, MemberSanction, ModerationLog, PostRelation
from app.posts.queries import RELATED_LIMIT
from tests.factories import make_board, make_member, make_post
from tests.helpers import as_member

pytestmark = pytest.mark.anyio


async def _world(db: AsyncSession):
    author = await make_member(db, level=1, display_name="글쓴이")
    other = await make_member(db, level=1, display_name="남")
    mod = await make_member(db, level=1, display_name="담당")
    board = await make_board(db, slug="free")
    db.add(BoardModerator(board_id=board.id, member_id=mod.id))
    source = await make_post(db, board, author, title="원본")
    targets = [await make_post(db, board, other, title=f"대상 {i}") for i in range(RELATED_LIMIT + 2)]
    await db.commit()
    return author, other, mod, board, source, targets


def _add(client, post_id: int, target_id: int, member_id: int):
    return client.post(f"/api/posts/{post_id}/relations", json={"target_id": target_id}, headers=as_member(member_id))


async def _count(db: AsyncSession, source_id: int) -> int:
    return (await db.execute(select(func.count()).select_from(PostRelation).where(PostRelation.source_post_id == source_id))).scalar_one()


async def test_author_adds_and_removes(dev_header, committed_db, client) -> None:
    author, _, _, _, source, targets = await _world(committed_db)
    res = await _add(client, source.id, targets[0].id, author.id)
    assert res.status_code == 200
    body = res.json()
    assert body["items"] == [{"id": targets[0].id, "title": "대상 0", "board_slug": "free", "readable": True}]
    assert body["invalidate"] == {"now": [f"post:{source.id}"], "max": []}
    again = (await _add(client, source.id, targets[0].id, author.id)).json()
    assert again["items"] == body["items"] and again["invalidate"] == {"now": [], "max": []}  # 멱등 — 바뀐 것이 없으면 캐시를 깨우지 않는다
    page = (await client.get(f"/api/posts/{source.id}/page")).json()
    assert [r["id"] for r in page["related"]] == [targets[0].id]  # 글 묶음 응답에 실린다
    res = await client.delete(f"/api/posts/{source.id}/relations/{targets[0].id}", headers=as_member(author.id))
    assert res.json()["items"] == []
    again = await client.delete(f"/api/posts/{source.id}/relations/{targets[0].id}", headers=as_member(author.id))
    assert again.status_code == 200 and again.json()["invalidate"] == {"now": [], "max": []}
    # 작성자 본인의 편집은 운영 기록에 남기지 않는다
    assert (await committed_db.execute(select(func.count()).select_from(ModerationLog))).scalar_one() == 0


async def test_who_may_edit(dev_header, committed_db, client) -> None:
    author, other, mod, _, source, targets = await _world(committed_db)
    assert (await client.post(f"/api/posts/{source.id}/relations", json={"target_id": targets[0].id})).status_code == 401
    res = await _add(client, source.id, targets[0].id, other.id)
    assert res.status_code == 403 and res.json()["code"] == "relations_forbidden"
    assert (await client.get(f"/api/posts/{source.id}/relations", headers=as_member(other.id))).status_code == 403
    assert (await _add(client, source.id, targets[0].id, mod.id)).status_code == 200
    log = (await committed_db.execute(select(ModerationLog))).scalar_one()  # 담당자가 남의 글을 바꾸면 기록
    assert (log.action, log.target_id, log.after) == ("post.relate", source.id, {"added": targets[0].id})
    committed_db.add(MemberSanction(member_id=author.id, actions=["write"], reason="시험", ends_at=datetime.now(UTC) + timedelta(days=1)))
    await committed_db.commit()
    assert (await _add(client, source.id, targets[1].id, author.id)).status_code == 403  # 정지 write 가 막는다
    assert (await _add(client, 999999, targets[1].id, mod.id)).status_code == 404


async def test_target_rules(dev_header, committed_db, client) -> None:
    author, other, _, board, source, _ = await _world(committed_db)
    secret = await make_post(committed_db, board, other, title="비밀", is_secret=True)
    draft = await make_post(committed_db, board, other, title="임시", status="draft")
    await committed_db.commit()
    for target in (secret.id, draft.id, 999999, source.id):
        res = await _add(client, source.id, target, author.id)
        assert res.status_code == 422, target
    assert await _count(committed_db, source.id) == 0


async def test_limit_holds_under_concurrency(dev_header, committed_db, client) -> None:
    author, _, _, _, source, targets = await _world(committed_db)
    for t in targets[: RELATED_LIMIT - 1]:
        assert (await _add(client, source.id, t.id, author.id)).status_code == 200
    # 남은 자리 하나에 동시 두 요청 — 하나만 들어간다(원본 글 행 잠금)
    a, b = await asyncio.gather(_add(client, source.id, targets[-2].id, author.id), _add(client, source.id, targets[-1].id, author.id))
    assert sorted([a.status_code, b.status_code]) == [200, 409]
    assert await _count(committed_db, source.id) == RELATED_LIMIT
    assert {a.json().get("code"), b.json().get("code")} >= {"relations_full"}


async def test_unreadable_target_stays_removable(dev_header, committed_db, client) -> None:
    author, other, _, board, source, targets = await _world(committed_db)
    await _add(client, source.id, targets[0].id, author.id)
    from sqlalchemy import update

    from app.models import Post

    await committed_db.execute(update(Post).where(Post.id == targets[0].id).values(is_secret=True))  # post-clause: exempt — 시험
    await committed_db.commit()
    items = (await client.get(f"/api/posts/{source.id}/relations", headers=as_member(author.id))).json()["items"]
    assert items == [{"id": targets[0].id, "title": None, "board_slug": None, "readable": False}]
    assert (await client.delete(f"/api/posts/{source.id}/relations/{targets[0].id}", headers=as_member(author.id))).json()["items"] == []
