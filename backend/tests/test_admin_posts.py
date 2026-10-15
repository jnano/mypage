"""글 관리(§5.3·§5.4·§6 bulk·§14.2 '글') — 일괄 조치·휴지통·복원·영구 삭제·옮기기·복사·고정·가림·승인."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    BoardCategory,
    BoardModerator,
    Comment,
    ModerationLog,
    Notification,
    Post,
    PostCategory,
    PostSearch,
    PostStat,
    PostTombstone,
)
from tests.factories import make_board, make_member, make_post
from tests.helpers import as_member


async def _world(db: AsyncSession, **board_kw):
    admin = await make_member(db, level=9, is_admin=True, display_name="운영")
    mod = await make_member(db, level=2, display_name="담당")
    author = await make_member(db, level=1, display_name="글쓴이")
    other = await make_member(db, level=1, display_name="남")
    free = await make_board(db, slug="free", **board_kw)
    news = await make_board(db, slug="news")
    db.add(BoardModerator(board_id=free.id, member_id=mod.id))
    posts = [await make_post(db, free, author, title=f"글 {i}") for i in range(3)]
    for p in posts:
        db.add(PostStat(post_id=p.id))
        db.add(PostSearch(post_id=p.id, board_id=free.id, published_at=p.published_at, post_open=True))
    await db.commit()
    return admin, mod, author, other, free, news, posts


async def _bulk(client, member_id: int, **body):
    return await client.post("/api/posts/bulk", json=body, headers=as_member(member_id))


async def _post(db: AsyncSession, post_id: int):
    return (await db.execute(select(Post).where(Post.id == post_id).execution_options(populate_existing=True))).scalar_one()  # post-clause: exempt — 시험


async def test_bulk_is_atomic_and_lists_forbidden_ids(dev_header, committed_db, client) -> None:
    admin, mod, author, other, free, news, posts = await _world(committed_db)
    elsewhere = await make_post(committed_db, news, author)
    await committed_db.commit()
    res = await _bulk(client, mod.id, ids=[posts[0].id, elsewhere.id], action="blind")
    assert res.status_code == 403 and res.json()["detail"] == f"ids={[elsewhere.id]}"
    assert (await _post(committed_db, posts[0].id)).is_blinded is False  # 하나도 바뀌지 않았다
    assert (await _bulk(client, mod.id, ids=[999999], action="trash")).status_code == 404
    assert (await _bulk(client, mod.id, ids=list(range(1, 102)), action="trash")).status_code == 422


async def test_trash_restore_purge(dev_header, committed_db, client) -> None:
    admin, mod, author, other, free, news, posts = await _world(committed_db, protect_commented_posts=True, trash_retention_days=30)
    p0, p1 = posts[0].id, posts[1].id
    # 작성자: 댓글이 달린 글은 지우지 못한다(protect_commented_posts), 남의 글도 못 지운다
    committed_db.add(Comment(post_id=p1, member_id=other.id, author_name_snapshot="남", content="댓글"))
    await committed_db.execute(PostStat.__table__.update().where(PostStat.post_id == p1).values(comment_count=1))
    await committed_db.commit()
    assert (await client.delete(f"/api/posts/{p1}", headers=as_member(author.id))).status_code == 403
    assert (await client.delete(f"/api/posts/{p0}", headers=as_member(other.id))).status_code == 403
    res = await client.delete(f"/api/posts/{p0}", headers=as_member(author.id))
    assert res.status_code == 200 and "board:free" in res.json()["invalidate"]["now"]
    trashed = await _post(committed_db, p0)
    assert trashed.status == "trashed" and trashed.trashed_from_status == "published"
    search_open = (await committed_db.execute(select(PostSearch.post_open).where(PostSearch.post_id == p0))).scalar_one()
    assert search_open is False
    # 관리 목록: 휴지통 글은 자동 정리 예정일
    listed = (await client.get("/api/admin/posts", params={"status": "trashed"}, headers=as_member(mod.id))).json()["items"]
    assert [i["id"] for i in listed] == [p0] and listed[0]["trash"]["purge_at"] is not None
    # 작성자는 복원 못 함(담당자만)
    assert (await client.post(f"/api/posts/{p0}/restore", headers=as_member(author.id))).status_code == 403
    assert (await client.post(f"/api/posts/{p0}/restore", headers=as_member(mod.id))).status_code == 200
    assert (await _post(committed_db, p0)).status == "published"
    # 영구 삭제는 휴지통 글만
    assert (await client.post(f"/api/posts/{p0}/purge", headers=as_member(mod.id))).json()["code"] == "not_in_trash"
    await client.delete(f"/api/posts/{p0}", headers=as_member(mod.id))
    assert (await client.post(f"/api/posts/{p0}/purge", json={"reason": "광고"}, headers=as_member(mod.id))).status_code == 200
    assert (await committed_db.execute(select(func.count()).select_from(PostTombstone))).scalar_one() == 1
    actions = (await committed_db.execute(select(ModerationLog.action).order_by(ModerationLog.id))).scalars().all()
    assert actions == ["post.trash", "post.restore", "post.trash", "post.purge"]
    log = (await committed_db.execute(select(ModerationLog).where(ModerationLog.action == "post.purge"))).scalar_one()
    assert log.before["author_id"] == author.id and log.reason == "광고"


async def test_move_and_copy(dev_header, committed_db, client) -> None:
    admin, mod, author, other, free, news, posts = await _world(committed_db)
    cat = BoardCategory(board_id=free.id, name="일반")
    committed_db.add(cat)
    await committed_db.flush()
    committed_db.add(PostCategory(post_id=posts[0].id, category_id=cat.id))
    await committed_db.commit()
    # 담당자는 맡지 않은 게시판으로 옮기지 못한다
    assert (await _bulk(client, mod.id, ids=[posts[0].id], action="move", board_id=news.id)).json()["code"] == "board_not_moderated"
    res = await _bulk(client, admin.id, ids=[posts[0].id], action="move", board_id=news.id)
    assert res.status_code == 200
    assert {"board:free", "board:news"} <= set(res.json()["invalidate"]["now"])
    moved = await _post(committed_db, posts[0].id)
    assert moved.board_id == news.id
    assert (await committed_db.execute(select(func.count()).select_from(PostCategory))).scalar_one() == 0
    assert (await committed_db.execute(select(PostSearch.board_id).where(PostSearch.post_id == moved.id))).scalar_one() == news.id
    note = (await committed_db.execute(select(Notification.type, Notification.recipient_id))).all()
    assert note == []  # moderation.moved 는 기본 수신 꺼짐(§7)
    # 복사: 그림은 빼고 사본을 만든다
    src = await make_post(committed_db, free, author, content_html='<p>앞</p><figure data-attachment-id="9" data-width="m"><img alt=""></figure>')
    await committed_db.commit()
    res = await _bulk(client, admin.id, ids=[src.id], action="copy", board_id=news.id)
    copy_id = res.json()["created"][0]
    copy = await _post(committed_db, copy_id)
    assert copy.board_id == news.id and copy.content_html == "<p>앞</p>" and copy.member_id == author.id
    assert (await _post(committed_db, src.id)).board_id == free.id


async def test_pin_order_blind_view_level(dev_header, committed_db, client) -> None:
    admin, mod, author, other, free, news, posts = await _world(committed_db)
    ids = [p.id for p in posts]
    await _bulk(client, mod.id, ids=ids, action="pin")
    orders = [(await _post(committed_db, i)).pin_order for i in ids]
    assert orders == [1, 2, 3]
    assert (await client.put("/api/boards/free/pinned/order", json={"ids": ids[::-1]}, headers=as_member(mod.id))).status_code == 200
    assert [(await _post(committed_db, i)).pin_order for i in ids] == [3, 2, 1]
    assert (await client.put("/api/boards/free/pinned/order", json={"ids": ids[:1]}, headers=as_member(mod.id))).status_code == 422
    # 가림: 검색에서 빠지고 작성자에게 알림
    await _bulk(client, mod.id, ids=[ids[0]], action="blind", reason="광고")
    assert (await committed_db.execute(select(PostSearch.post_open).where(PostSearch.post_id == ids[0]))).scalar_one() is False
    notes = (await committed_db.execute(select(Notification.type, Notification.recipient_id))).all()
    assert notes == [("moderation.blinded", author.id)]
    await _bulk(client, mod.id, ids=[ids[0]], action="unblind")
    assert (await committed_db.execute(select(PostSearch.post_open).where(PostSearch.post_id == ids[0]))).scalar_one() is True
    await _bulk(client, mod.id, ids=[ids[1]], action="view_level", min_view_level=3)
    assert (await _post(committed_db, ids[1])).min_view_level == 3
    assert (await committed_db.execute(select(PostSearch.post_open).where(PostSearch.post_id == ids[1]))).scalar_one() is False


async def test_approve_reject_publish_now(dev_header, committed_db, client) -> None:
    admin, mod, author, other, free, news, posts = await _world(committed_db)
    pending = await make_post(committed_db, free, author, status="pending", published_at=None)
    pending2 = await make_post(committed_db, free, author, status="pending", published_at=None)
    sched = await make_post(committed_db, free, author, status="scheduled", published_at=datetime.now(UTC) + timedelta(days=1))
    for p in (pending, pending2, sched):
        committed_db.add(PostSearch(post_id=p.id, board_id=free.id, published_at=p.published_at, post_open=False))
    await committed_db.commit()
    queue = (await client.get("/api/admin/pending", headers=as_member(mod.id))).json()["items"]
    assert {i["id"] for i in queue} == {pending.id, pending2.id}
    assert (await client.post(f"/api/posts/{pending.id}/approve", headers=as_member(author.id))).status_code == 403
    assert (await client.post(f"/api/posts/{pending.id}/approve", headers=as_member(mod.id))).status_code == 200
    approved = await _post(committed_db, pending.id)
    assert approved.status == "published" and approved.published_at is not None
    assert (await client.post(f"/api/posts/{pending2.id}/reject", json={}, headers=as_member(mod.id))).status_code == 422  # 사유 필수
    assert (await client.post(f"/api/posts/{pending2.id}/reject", json={"reason": "중복"}, headers=as_member(mod.id))).status_code == 200
    assert (await _post(committed_db, pending2.id)).status == "trashed"
    assert (await _bulk(client, mod.id, ids=[sched.id], action="publish_now")).status_code == 200
    assert (await _post(committed_db, sched.id)).status == "published"
    # 판정 표(§5.3): 승인 대상은 pending — 판정에서 먼저 거부된다
    assert (await _bulk(client, mod.id, ids=[posts[0].id], action="approve")).json()["code"] == "bulk_forbidden"


async def test_patch_moderate_fields(dev_header, committed_db, client) -> None:
    admin, mod, author, other, free, news, posts = await _world(committed_db, allow_title_style=True)
    p = posts[0]
    h = as_member(mod.id) | {"If-Match": f'"{p.version}"'}
    # 작성자는 관리 칸을 못 바꾼다
    assert (await client.patch(f"/api/posts/{p.id}", json={"title_bold": True}, headers=as_member(author.id) | {"If-Match": f'"{p.version}"'})).status_code == 403
    res = await client.patch(f"/api/posts/{p.id}", json={"title_bold": True, "title_color": "red"}, params={"reason": "강조"}, headers=h)
    assert res.status_code == 200, res.text
    version = res.json()["post"]["version"]
    post = await _post(committed_db, p.id)
    assert post.title_bold is True and post.title_color == "red" and post.version == version
    assert (await client.patch(f"/api/posts/{p.id}", json={"title_color": "crimson"}, headers=as_member(mod.id) | {"If-Match": f'"{version}"'})).status_code == 422
    assert (await client.patch(f"/api/posts/{p.id}", json={"is_pinned": True}, headers=as_member(mod.id) | {"If-Match": '"1"'})).status_code == 412
    res = await client.patch(f"/api/posts/{p.id}", json={"is_pinned": True}, headers=as_member(mod.id) | {"If-Match": f'"{version}"'})
    assert res.status_code == 200 and (await _post(committed_db, p.id)).is_pinned
    assert (await client.patch(f"/api/posts/{p.id}", json={"title": "새", "is_pinned": False}, headers=h)).status_code == 422  # 섞지 않는다


async def test_admin_list_filters_and_scope(dev_header, committed_db, client) -> None:
    admin, mod, author, other, free, news, posts = await _world(committed_db)
    await make_post(committed_db, news, other, title="소식 하나")
    await committed_db.commit()
    as_mod = (await client.get("/api/admin/posts", headers=as_member(mod.id))).json()["items"]
    assert {i["board"]["slug"] for i in as_mod} == {"free"}
    as_admin = (await client.get("/api/admin/posts", headers=as_member(admin.id))).json()["items"]
    assert len(as_admin) == 4
    found = (await client.get("/api/admin/posts", params={"q": "소식"}, headers=as_member(admin.id))).json()["items"]
    assert [i["title"] for i in found] == ["소식 하나"]
    by_author = (await client.get("/api/admin/posts", params={"author_id": other.id}, headers=as_member(admin.id))).json()["items"]
    assert len(by_author) == 1
    assert (await client.get("/api/admin/posts", params={"status": "nope"}, headers=as_member(admin.id))).json()["items"] == []
