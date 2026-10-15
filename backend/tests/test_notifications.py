"""알림(§7) — 댓글·답글·구독 새 글·승인 대기, 묶음·수신 설정·행위자 제외, 알림함 가림, 읽음, 설정·구독 API."""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import outbox
from app.db.session import SessionLocal
from app.notifications import queries as nq
from app.models import (
    BoardAccess,
    BoardModerator,
    BoardSubscription,
    MemberGroup,
    MemberGroupMember,
    Notification,
    NotificationPref,
    Post,
    PostStat,
)
from app.worker import handlers  # noqa: F401 — 처리기 등록
from app.worker.core import process_available
from tests.factories import make_board, make_member, make_post
from tests.helpers import as_member

pytestmark = pytest.mark.anyio


async def _notes(db: AsyncSession, member_id: int | None = None) -> list[Notification]:
    db.expire_all()
    stmt = select(Notification).order_by(Notification.id)
    if member_id is not None:
        stmt = stmt.where(Notification.recipient_id == member_id)
    return list((await db.execute(stmt)).scalars())


async def _comment(client: AsyncClient, post_id: int, member_id: int, reply_to: int | None = None) -> int:
    body = {"content": "댓글"} | ({"reply_to": reply_to} if reply_to else {})
    res = await client.post(f"/api/posts/{post_id}/comments", json=body, headers=as_member(member_id))
    assert res.status_code == 201, res.text
    return res.json()["comment"]["id"]


async def _setup(db: AsyncSession):
    author = await make_member(db, display_name="글쓴이")
    alice = await make_member(db, display_name="가람")
    bob = await make_member(db, display_name="나래")
    board = await make_board(db, slug="free")
    post = await make_post(db, board, author, title="회의 안내")
    db.add(PostStat(post_id=post.id))
    await db.commit()
    return author, alice, bob, board, post


# ── 댓글 알림 ─────────────────────────────────────────────


async def test_comment_notifications_and_grouping(dev_header, committed_db, client) -> None:
    author, alice, bob, _, post = await _setup(committed_db)
    a_id, author_id, bob_id, post_id = alice.id, author.id, bob.id, post.id
    await _comment(client, post_id, a_id)
    await _comment(client, post_id, bob_id)
    await _comment(client, post_id, author_id)  # 자기 글에 쓴 댓글은 알리지 않는다
    await process_available(50)

    [note] = await _notes(committed_db, author_id)
    assert (note.type, note.actor_count, note.actor_id, note.title_snapshot) == ("comment.on_my_post", 2, bob_id, "회의 안내")

    # 읽은 뒤의 새 사건은 새 행
    await committed_db.execute(update(Notification).values(read_at=datetime.now(UTC)))
    await committed_db.commit()
    await _comment(client, post_id, a_id)
    await process_available(50)
    assert [n.actor_count for n in await _notes(committed_db, author_id)] == [2, 1]


async def test_reply_notifies_replied_person_once(dev_header, committed_db, client) -> None:
    author, alice, bob, _, post = await _setup(committed_db)
    a_id, author_id, bob_id = alice.id, author.id, bob.id
    root = await _comment(client, post.id, a_id)
    await _comment(client, post.id, bob_id, reply_to=root)  # 가람에게 답글, 글쓴이에게 댓글 알림
    mine = await _comment(client, post.id, author_id)
    await _comment(client, post.id, bob_id, reply_to=mine)  # 글쓴이에게 답글 — 댓글 알림과 겹치면 하나만
    await process_available(50)

    assert [(n.type, n.actor_id) for n in await _notes(committed_db, a_id)] == [("comment.reply", bob_id)]
    author_notes = [(n.type, n.actor_count) for n in await _notes(committed_db, author_id)]
    assert author_notes == [("comment.on_my_post", 2), ("comment.reply", 1)]


async def test_pref_off_and_withdrawn(dev_header, committed_db, client) -> None:
    author, alice, _, _, post = await _setup(committed_db)
    committed_db.add(NotificationPref(member_id=author.id, type="comment.on_my_post", enabled=False))
    await committed_db.commit()
    await _comment(client, post.id, alice.id)
    await process_available(50)
    assert await _notes(committed_db) == []


# ── 구독한 게시판의 새 글: 받는 사람은 SQL 한 번 ───────────────


async def test_board_new_post_recipients(dev_header, committed_db, client) -> None:
    db = committed_db
    writer = await make_member(db, level=3)
    low = await make_member(db, level=1)
    high = await make_member(db, level=3)
    mod = await make_member(db, level=1)
    grouped = await make_member(db, level=1)
    gone = await make_member(db, level=3, status="withdrawn", withdrawn_at=datetime.now(UTC))
    group = MemberGroup(name="회의 참석자")
    db.add(group)
    board = await make_board(db, slug="members", list_level=2, read_level=2, write_level=1, editor="markdown", allow_secret=True)
    await db.flush()
    db.add_all(
        [
            MemberGroupMember(group_id=group.id, member_id=grouped.id),
            BoardAccess(board_id=board.id, subject_type="group", subject_id=group.id, can_read=True),
            BoardModerator(board_id=board.id, member_id=mod.id),
            *[BoardSubscription(board_id=board.id, member_id=m.id) for m in (writer, low, high, mod, grouped, gone)],
        ]
    )
    await db.commit()
    ids = {k: m.id for k, m in dict(writer=writer, low=low, high=high, mod=mod, grouped=grouped).items()}

    res = await client.post("/api/boards/members/posts", json={"title": "모집 공고", "content": "본문"}, headers=as_member(ids["writer"]))
    secret = await client.post(
        "/api/boards/members/posts", json={"title": "비공개", "content": "본문", "is_secret": True}, headers=as_member(ids["writer"])
    )
    assert res.status_code == secret.status_code == 201
    await process_available(50)

    notes = await _notes(db)
    got = {(n.recipient_id, n.actor_count) for n in notes}
    # 공개 글: 레벨 3·명부(그룹)·담당자 / 비밀글: 담당자만 → 담당자는 묶여 2
    assert got == {(ids["high"], 1), (ids["grouped"], 1), (ids["mod"], 2)}
    assert {n.type for n in notes} == {"board.new_post"}
    # 제목은 '게시판 이름 · 글 제목'(묶이면 마지막 글)
    assert {n.title_snapshot for n in notes} == {"자유게시판 · 모집 공고", "자유게시판 · 비공개"}


async def test_pending_post_notifies_moderators(committed_db) -> None:
    db = committed_db
    mod = await make_member(db)
    board = await make_board(db, slug="free")
    db.add(BoardModerator(board_id=board.id, member_id=mod.id))
    post = await make_post(db, board, None, status="pending", is_guest=True, guest_password_hash="h", title="비회원 글")
    await db.commit()
    mod_id, post_id, board_id = mod.id, post.id, board.id
    async with SessionLocal() as s, s.begin():
        await outbox.enqueue(s, [outbox.Event("post.created", {"post_id": post_id, "board_id": board_id})])
    await process_available(10)
    [note] = await _notes(db)
    assert (note.recipient_id, note.type, note.actor_id) == (mod_id, "admin.guest_pending", None)


# ── 알림함 ───────────────────────────────────────────────


async def test_inbox_masks_unreadable_and_deleted(dev_header, committed_db, client) -> None:
    author, alice, _, board, post = await _setup(committed_db)
    other = await make_post(committed_db, board, author, title="다른 글")
    committed_db.add(PostStat(post_id=other.id))
    await committed_db.commit()
    post_id, other_id, author_id = post.id, other.id, author.id
    await _comment(client, post_id, alice.id)
    await _comment(client, other_id, alice.id)
    await process_available(50)
    # 한 글은 블라인드(글쓴이도 못 엶 → 제목 가림), 한 글은 영구 삭제(→ '삭제된 글')
    await committed_db.execute(update(Post).where(Post.id == other_id).values(is_blinded=True, blind_source="manual"))
    await committed_db.execute(delete(Post).where(Post.id == post_id))
    await committed_db.commit()

    body = (await client.get("/api/me/notifications", headers=as_member(author_id))).json()
    by_masked = {i["masked"]: i for i in body["items"]}
    assert set(by_masked) == {"deleted", "hidden"}
    assert all(i["title"] is None and i["path"] is None for i in body["items"])


async def test_inbox_paging_read_and_badge(dev_header, committed_db, client, monkeypatch) -> None:
    monkeypatch.setattr(nq, "PAGE_SIZE", 2)
    author, alice, _, _, post = await _setup(committed_db)
    author_id = author.id
    for i in range(3):
        committed_db.add(
            Notification(recipient_id=author_id, type="comment.on_my_post", post_id=post.id, title_snapshot=f"t{i}",
                         group_key=f"g{i}", dedupe_key=f"d{i}")  # fmt: skip
        )
    await committed_db.commit()
    h = as_member(author_id)
    first = (await client.get("/api/me/notifications", headers=h)).json()
    assert len(first["items"]) == 2 and first["items"][0]["path"] == f"/boards/free/{post.id}"
    rest = (await client.get("/api/me/notifications", params={"cursor": first["next_cursor"]}, headers=h)).json()
    assert len(rest["items"]) == 1 and rest["next_cursor"] is None

    assert (await client.get("/api/me/page-state?board=free", headers=h)).json()["unread_notifications"] == 3
    assert (await client.post("/api/me/notifications/read", json={"ids": [first["items"][0]["id"]]}, headers=h)).json() == {"read": 1}
    assert (await client.post("/api/me/notifications/read", json={"all": True}, headers=h)).json() == {"read": 2}
    assert (await client.get("/api/me/page-state?board=free", headers=h)).json()["unread_notifications"] == 0
    assert (await client.post("/api/me/notifications/read", json={}, headers=h)).status_code == 422
    assert (await client.get("/api/me/notifications")).status_code == 401


async def test_prefs_and_subscription_api(dev_header, committed_db, client) -> None:
    member = await make_member(committed_db)
    await make_board(committed_db, slug="free")
    await make_board(committed_db, slug="closed", list_level=5)
    await committed_db.commit()
    h = as_member(member.id)

    prefs = {i["type"]: i["enabled"] for i in (await client.get("/api/me/notification-prefs", headers=h)).json()["items"]}
    assert prefs["comment.on_my_post"] is True and prefs["moderation.moved"] is False and len(prefs) == 8
    res = await client.put("/api/me/notification-prefs", json={"comment.reply": False}, headers=h)
    assert {i["type"]: i["enabled"] for i in res.json()["items"]}["comment.reply"] is False
    assert (await client.put("/api/me/notification-prefs", json={"nope": True}, headers=h)).status_code == 422

    assert (await client.put("/api/boards/free/subscription", headers=h)).json() == {"subscribed": True}
    assert (await client.put("/api/boards/free/subscription", headers=h)).json() == {"subscribed": True}  # 멱등
    assert (await client.get("/api/me/page-state?board=free", headers=h)).json()["subscribed"] is True
    assert (await client.delete("/api/boards/free/subscription", headers=h)).json() == {"subscribed": False}
    assert (await client.put("/api/boards/closed/subscription", headers=h)).status_code == 403
