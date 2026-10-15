"""신고·댓글 관리·제재(§5.3·§6·§14.2)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BoardModerator, Comment, MemberSanction, ModerationLog, Notification, Post, PostSearch, PostStat, Report
from tests.factories import make_board, make_member, make_post
from tests.helpers import as_member


async def _world(db: AsyncSession, **board_kw):
    admin = await make_member(db, level=9, is_admin=True, display_name="운영")
    mod = await make_member(db, level=2, display_name="담당")
    author = await make_member(db, level=1, display_name="글쓴이")
    r1 = await make_member(db, level=1, display_name="신고하나")
    r2 = await make_member(db, level=1, display_name="신고둘")
    board = await make_board(db, slug="free", **board_kw)
    other = await make_board(db, slug="other")
    db.add(BoardModerator(board_id=board.id, member_id=mod.id))
    post = await make_post(db, board, author, title="문제 글")
    db.add(PostStat(post_id=post.id, comment_count=1))
    db.add(PostSearch(post_id=post.id, board_id=board.id, published_at=post.published_at, post_open=True))
    comment = Comment(post_id=post.id, member_id=author.id, author_name_snapshot="글쓴이", content="문제 댓글입니다")
    db.add(comment)
    await db.commit()
    return admin, mod, author, r1, r2, board, other, post, comment


async def _report(client, member_id, target_type, target_id, code="spam", **headers):
    return await client.post(
        "/api/reports", json={"target_type": target_type, "target_id": target_id, "reason_code": code}, headers=as_member(member_id) | headers
    )


async def test_report_create_rules(dev_header, committed_db, client) -> None:
    admin, mod, author, r1, r2, board, other, post, comment = await _world(committed_db)
    assert (await client.post("/api/reports", json={"target_type": "post", "target_id": post.id, "reason_code": "spam"})).status_code == 401
    assert (await _report(client, r1.id, "post", post.id, code="nope")).status_code == 422
    first = await _report(client, r1.id, "post", post.id, **{"Idempotency-Key": "k1"})
    assert first.status_code == 201
    replay = await _report(client, r1.id, "post", post.id, **{"Idempotency-Key": "k1"})
    assert replay.status_code == 201 and replay.json() == first.json()
    assert (await _report(client, r1.id, "post", post.id)).json()["code"] == "already_reported"
    assert (await _report(client, r1.id, "comment", comment.id)).status_code == 201
    assert (await _report(client, r1.id, "post", 999999)).status_code == 404
    # 담당자에게 알림(신고 접수)
    notes = (await committed_db.execute(select(Notification.type, Notification.recipient_id))).all()
    assert ("admin.report", mod.id) in notes


async def test_auto_blind_threshold_and_dismiss_unblinds(dev_header, committed_db, client) -> None:
    admin, mod, author, r1, r2, board, other, post, comment = await _world(committed_db, report_auto_blind_threshold=2)
    await _report(client, r1.id, "post", post.id)
    assert (await committed_db.execute(select(Post.is_blinded).where(Post.id == post.id))).scalar_one() is False  # post-clause: exempt — 시험
    res = await _report(client, r2.id, "post", post.id)
    assert "board:free" in res.json()["invalidate"]["now"]
    row = (await committed_db.execute(select(Post.is_blinded, Post.blind_source).where(Post.id == post.id))).one()  # post-clause: exempt — 시험
    assert tuple(row) == (True, "auto_report")
    assert (await committed_db.execute(select(PostSearch.post_open).where(PostSearch.post_id == post.id))).scalar_one() is False
    log = (await committed_db.execute(select(ModerationLog).where(ModerationLog.action == "post.auto_blind"))).scalar_one()
    assert log.actor_id is None
    queue = (await client.get("/api/admin/reports", headers=as_member(mod.id))).json()["items"]
    assert len(queue) == 1 and queue[0]["count"] == 2 and queue[0]["target"]["blinded"] is True
    # 기각하면 자동 가림을 푼다 — 사유 필수
    rid = queue[0]["report_id"]
    assert (await client.post(f"/api/admin/reports/{rid}/resolve", json={"action": "dismiss"}, headers=as_member(mod.id))).status_code == 422
    res = await client.post(f"/api/admin/reports/{rid}/resolve", json={"action": "dismiss", "reason": "문제 없음"}, headers=as_member(mod.id))
    assert res.status_code == 200 and res.json()["resolved"] == 2
    assert (await committed_db.execute(select(Post.is_blinded).where(Post.id == post.id))).scalar_one() is False  # post-clause: exempt — 시험
    statuses = set((await committed_db.execute(select(Report.status))).scalars())
    assert statuses == {"dismissed"}
    assert (await client.get("/api/admin/reports", headers=as_member(mod.id))).json()["items"] == []
    notes = (await committed_db.execute(select(Notification.type, Notification.recipient_id).where(Notification.type == "report.resolved"))).all()
    assert notes == []  # report.resolved 기본 수신 꺼짐(§7)


async def test_resolve_with_trash_and_sanction(dev_header, committed_db, client) -> None:
    admin, mod, author, r1, r2, board, other, post, comment = await _world(committed_db)
    await _report(client, r1.id, "post", post.id)
    rid = (await client.get("/api/admin/reports", headers=as_member(mod.id))).json()["items"][0]["report_id"]
    # 담당자는 사이트 전체 정지를 걸 수 없다(트랜잭션 전체가 되돌아간다)
    body = {"action": "trash", "reason": "광고", "sanction": {"actions": ["write"], "days": 7, "site_wide": True}}
    assert (await client.post(f"/api/admin/reports/{rid}/resolve", json=body, headers=as_member(mod.id))).json()["code"] == "admin_only"
    assert (await committed_db.execute(select(Post.status).where(Post.id == post.id))).scalar_one() == "published"  # post-clause: exempt — 시험
    body["sanction"]["site_wide"] = False
    res = await client.post(f"/api/admin/reports/{rid}/resolve", json=body, headers=as_member(mod.id))
    assert res.status_code == 200 and res.json()["sanction_id"]
    assert (await committed_db.execute(select(Post.status).where(Post.id == post.id))).scalar_one() == "trashed"  # post-clause: exempt — 시험
    sanction = (await committed_db.execute(select(MemberSanction))).scalar_one()
    assert sanction.member_id == author.id and sanction.scope_board_id == board.id and sanction.actions == ["write"]
    # 판정: 그 게시판에 글쓰기가 막힌다(다른 게시판은 된다)
    new = await client.post("/api/boards/free/posts", json={"title": "또", "content": "본문"}, headers=as_member(author.id))
    assert new.status_code == 403
    assert (await client.post("/api/boards/other/posts", json={"title": "다른 곳", "content": "본문"}, headers=as_member(author.id))).status_code == 201
    # 담당자 목록에 보이고, 풀면 다시 쓸 수 있다
    listed = (await client.get("/api/admin/sanctions", headers=as_member(mod.id))).json()["items"]
    assert [s["member"]["name"] for s in listed] == ["글쓴이"]
    assert (await client.delete(f"/api/admin/sanctions/{sanction.id}", headers=as_member(mod.id))).status_code == 200
    assert (await client.post("/api/boards/free/posts", json={"title": "또", "content": "본문"}, headers=as_member(author.id))).status_code == 201


async def test_comment_reports_and_bulk(dev_header, committed_db, client) -> None:
    admin, mod, author, r1, r2, board, other, post, comment = await _world(committed_db)
    await _report(client, r1.id, "comment", comment.id)
    item = (await client.get("/api/admin/reports", headers=as_member(mod.id))).json()["items"][0]
    assert item["target"]["title"] == "문제 댓글입니다" and item["target"]["post_id"] == post.id
    assert (await client.post(f"/api/admin/reports/{item['report_id']}/resolve", json={"action": "trash", "reason": "x"}, headers=as_member(mod.id))).status_code == 422
    res = await client.post(f"/api/admin/reports/{item['report_id']}/resolve", json={"action": "blind", "reason": "욕설"}, headers=as_member(mod.id))
    assert res.status_code == 200 and f"post:{post.id}" in res.json()["invalidate"]["now"]
    assert (await committed_db.execute(select(Comment.is_blinded).where(Comment.id == comment.id))).scalar_one() is True
    listed = (await client.get("/api/admin/comments", params={"blinded": True}, headers=as_member(mod.id))).json()["items"]
    assert [c["id"] for c in listed] == [comment.id]
    # 일괄 삭제(소프트) — 댓글 수도 준다. 일반 회원은 못 한다
    assert (await client.post("/api/comments/bulk", json={"ids": [comment.id], "action": "delete"}, headers=as_member(r1.id))).status_code == 403
    assert (await client.post("/api/comments/bulk", json={"ids": [comment.id], "action": "delete"}, headers=as_member(mod.id))).status_code == 200
    assert (await committed_db.execute(select(Comment.status).where(Comment.id == comment.id))).scalar_one() == "deleted"
    assert (await committed_db.execute(select(PostStat.comment_count).where(PostStat.post_id == post.id))).scalar_one() == 0
    log = (await committed_db.execute(select(ModerationLog).where(ModerationLog.action == "comment.delete"))).scalar_one()
    assert log.before["excerpt"] == "문제 댓글입니다" and log.before["author_id"] == author.id


async def test_sanction_scope_rules(dev_header, committed_db, client) -> None:
    admin, mod, author, r1, r2, board, other, post, comment = await _world(committed_db)
    base = {"member_id": author.id, "actions": ["comment"], "reason": "도배"}
    assert (await client.post("/api/admin/sanctions", json=base | {"board_id": other.id}, headers=as_member(mod.id))).json()["code"] == "board_not_moderated"
    assert (await client.post("/api/admin/sanctions", json=base | {"site_wide": True}, headers=as_member(mod.id))).json()["code"] == "admin_only"
    assert (await client.post("/api/admin/sanctions", json=base, headers=as_member(admin.id))).status_code == 422  # 범위를 골라야 한다
    assert (await client.post("/api/admin/sanctions", json=base | {"site_wide": True, "member_id": admin.id}, headers=as_member(admin.id))).json()["code"] == "admin_not_sanctionable"
    res = await client.post("/api/admin/sanctions", json=base | {"site_wide": True, "days": 1}, headers=as_member(admin.id))
    assert res.status_code == 201
    # 사이트 전체 정지: 모든 게시판에서 댓글이 막힌다
    assert (await client.post(f"/api/posts/{post.id}/comments", json={"content": "또"}, headers=as_member(author.id))).status_code == 403
    # 담당자에게는 사이트 전체 정지가 보이지 않는다
    assert (await client.get("/api/admin/sanctions", headers=as_member(mod.id))).json()["items"] == []
    assert len((await client.get("/api/admin/sanctions", headers=as_member(admin.id))).json()["items"]) == 1
