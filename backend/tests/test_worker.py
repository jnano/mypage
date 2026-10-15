"""작업자(§3.2) — outbox 처리·재시도·동시성, 처리기, 영구 삭제(§4.6), 주기 작업, 일정, LISTEN."""

import asyncio
import json
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import outbox
from app.core.config import settings
from app.db.session import SessionLocal
from app.models import (
    BoardDailyStat,
    Comment,
    IdempotencyKey,
    Member,
    Notification,
    OutboxEvent,
    Post,
    PostSearch,
    PostTombstone,
    PostViewDaily,
    PostViewOnce,
    RateLimitCounter,
    Report,
    WorkerSchedule,
)
from app.posts.purge import purge_posts
from app.worker import handlers, jobs
from app.worker.core import HANDLERS, MAX_ATTEMPTS, process_available, process_one
from app.worker.main import run
from app.worker.schedules import ensure_schedules, run_due_one
from tests.factories import make_board, make_member, make_post

pytestmark = pytest.mark.anyio
NOW = datetime.now(UTC)


async def _enqueue(*events: outbox.Event) -> None:
    async with SessionLocal() as db, db.begin():
        await outbox.enqueue(db, list(events))


async def _events(db: AsyncSession) -> list[OutboxEvent]:
    db.expire_all()
    return list((await db.execute(select(OutboxEvent).order_by(OutboxEvent.id))).scalars())


# ── 처리·재시도 ───────────────────────────────────────────


async def test_processes_and_marks_done(committed_db: AsyncSession, monkeypatch) -> None:
    seen = []

    async def ok(_db, event):
        seen.append(event.payload["n"])

    monkeypatch.setitem(HANDLERS, "test.ok", ok)
    await _enqueue(*(outbox.Event("test.ok", {"n": i}) for i in range(3)))
    assert await process_available(10) == 3
    assert seen == [0, 1, 2]
    assert all(e.processed_at is not None and e.attempts == 0 for e in await _events(committed_db))
    assert await process_one() is False


async def test_failure_backs_off_then_dies(committed_db: AsyncSession, monkeypatch) -> None:
    async def boom(db, _event):
        # 처리기가 남긴 DB 변경은 실패와 함께 되돌려져야 한다(SAVEPOINT)
        await db.execute(text("INSERT INTO search_terms (term, count, last_searched_at) VALUES ('흔적', 1, now())"))
        raise RuntimeError("실패")

    monkeypatch.setitem(HANDLERS, "test.boom", boom)
    await _enqueue(outbox.Event("test.boom"))
    assert await process_one() is True
    [event] = await _events(committed_db)
    assert (event.attempts, event.processed_at, event.dead_at) == (1, None, None)
    assert "RuntimeError: 실패" in event.last_error and event.available_at > datetime.now(UTC)
    assert await process_one() is False  # 백오프 동안은 줍지 않는다
    assert (await committed_db.execute(text("SELECT count(*) FROM search_terms"))).scalar_one() == 0

    for _ in range(MAX_ATTEMPTS - 1):
        await committed_db.execute(update(OutboxEvent).values(available_at=func.now()))
        await committed_db.commit()
        await process_one()
    [event] = await _events(committed_db)
    assert event.attempts == MAX_ATTEMPTS and event.dead_at is not None and event.processed_at is None


async def test_unknown_event_type_is_retried_not_dropped(committed_db: AsyncSession) -> None:
    await _enqueue(outbox.Event("test.nobody"))
    await process_one()
    [event] = await _events(committed_db)
    assert event.attempts == 1 and "처리기가 없는 이벤트" in event.last_error


async def test_future_event_waits(committed_db: AsyncSession, monkeypatch) -> None:
    monkeypatch.setitem(HANDLERS, "test.ok", lambda *_: asyncio.sleep(0))
    await _enqueue(outbox.Event("test.ok", available_at=NOW + timedelta(hours=1)))
    assert await process_one() is False


async def test_two_workers_process_each_event_once(committed_db: AsyncSession, monkeypatch) -> None:
    calls: list[int] = []

    async def slow(_db, event):
        calls.append(event.id)
        await asyncio.sleep(0.01)

    monkeypatch.setitem(HANDLERS, "test.slow", slow)
    await _enqueue(*(outbox.Event("test.slow") for _ in range(20)))
    a, b = await asyncio.gather(process_available(100), process_available(100))
    assert a + b == 20 and sorted(calls) == sorted(set(calls)) and len(calls) == 20


# ── 처리기 ───────────────────────────────────────────────


async def test_cache_revalidate_posts_to_next(committed_db: AsyncSession, monkeypatch) -> None:
    sent = []

    def respond(request: httpx.Request) -> httpx.Response:
        sent.append((str(request.url), request.headers.get("x-internal-secret"), json.loads(request.content)))
        return httpx.Response(200 if len(sent) > 1 else 503)

    monkeypatch.setattr(handlers, "transport", httpx.MockTransport(respond))
    await _enqueue(outbox.Event("cache.revalidate", {"now": ["post:1"], "max": ["sitemap"]}))
    await process_one()  # 503 → 재시도
    [event] = await _events(committed_db)
    assert event.attempts == 1 and event.processed_at is None
    await committed_db.execute(update(OutboxEvent).values(available_at=func.now()))
    await committed_db.commit()
    await process_one()
    [event] = await _events(committed_db)
    assert event.processed_at is not None
    assert sent[-1] == (settings.next_revalidate_url, settings.internal_api_secret, {"now": ["post:1"], "max": ["sitemap"]})


async def test_publish_scheduled(committed_db: AsyncSession) -> None:
    board = await make_board(committed_db, slug="free")
    due = await make_post(committed_db, board, None, status="scheduled", published_at=NOW - timedelta(minutes=1))
    later = await make_post(committed_db, board, None, status="scheduled", published_at=NOW + timedelta(days=1))
    for p in (due, later):
        committed_db.add(PostSearch(post_id=p.id, board_id=board.id, post_open=False, published_at=p.published_at))
    await committed_db.commit()
    await _enqueue(
        outbox.Event("post.publish_scheduled", {"post_id": due.id}, available_at=NOW - timedelta(minutes=1)),
        # 예약이 하루 뒤로 바뀐 글의 옛 이벤트 — 아무것도 하지 않아야 한다
        outbox.Event("post.publish_scheduled", {"post_id": later.id}, available_at=NOW - timedelta(minutes=1)),
    )
    due_id, later_id = due.id, later.id
    await process_available(10)
    committed_db.expire_all()
    status = dict((await committed_db.execute(select(Post.id, Post.status))).all())
    assert status == {due_id: "published", later_id: "scheduled"}
    opened = dict((await committed_db.execute(select(PostSearch.post_id, PostSearch.post_open))).all())
    assert opened == {due_id: True, later_id: False}
    revalidates = [e for e in await _events(committed_db) if e.type == "cache.revalidate"]
    assert [r.payload for r in revalidates] == [
        {"now": [f"post:{due_id}", "board:free", "recent:posts"], "max": ["boards:activity", "sitemap", "feed:free"]}
    ]


# ── 영구 삭제(§4.6) ──────────────────────────────────────


async def test_purge_posts(committed_db: AsyncSession) -> None:
    db = committed_db
    member = await make_member(db)
    board = await make_board(db, slug="free")
    post = await make_post(db, board, member)
    keep = await make_post(db, board, member)
    comment = Comment(post_id=post.id, member_id=member.id, author_name_snapshot="회원", content="댓글")
    db.add(comment)
    await db.flush()
    db.add_all(
        [
            Report(target_type="post", target_id=post.id, board_id=board.id, reason_code="spam"),
            Report(target_type="comment", target_id=comment.id, board_id=board.id, reason_code="spam"),
            Report(target_type="post", target_id=keep.id, board_id=board.id, reason_code="spam"),
            Notification(recipient_id=member.id, type="comment.on_my_post", post_id=post.id, title_snapshot="t", group_key="g", dedupe_key="d"),
        ]
    )
    await db.commit()
    post_id, keep_id = post.id, keep.id

    async with SessionLocal() as s, s.begin():
        assert await purge_posts(s, [post_id, 999_999]) == 1
    db.expire_all()
    assert (await db.execute(select(Post.id))).scalars().all() == [keep_id]
    assert (await db.execute(select(PostTombstone.post_id, PostTombstone.board_slug))).all() == [(post_id, "free")]
    statuses = dict((await db.execute(select(Report.target_id, Report.status).where(Report.target_type == "post"))).all())
    assert statuses == {post_id: "resolved_deleted", keep_id: "open"}
    assert (await db.execute(select(Report.status).where(Report.target_type == "comment"))).scalar_one() == "resolved_deleted"
    assert (await db.execute(select(Notification.post_id))).scalar_one() is None
    assert [e.type for e in await _events(db)] == ["cache.revalidate"]


# ── 주기 작업 ─────────────────────────────────────────────


async def test_trash_purge_respects_retention(committed_db: AsyncSession) -> None:
    db = committed_db
    kept_board = await make_board(db, slug="keep")  # trash_retention_days 없음 → 정리 안 함
    board = await make_board(db, slug="free", trash_retention_days=30)
    old = dict(status="trashed", trashed_from_status="published")
    expired = await make_post(db, board, None, trashed_at=NOW - timedelta(days=31), **old)
    fresh = await make_post(db, board, None, trashed_at=NOW - timedelta(days=29), **old)
    untouched = await make_post(db, kept_board, None, trashed_at=NOW - timedelta(days=400), **old)
    await db.commit()
    async with SessionLocal() as s, s.begin():
        assert await jobs.purge_trash(s) == 1
    assert set((await db.execute(select(Post.id))).scalars()) == {fresh.id, untouched.id}
    assert (await db.execute(select(PostTombstone.post_id))).scalar_one() == expired.id


async def test_cleanup_notifications(committed_db: AsyncSession, monkeypatch) -> None:
    monkeypatch.setattr(jobs, "NOTIFICATIONS_PER_MEMBER", 3)
    db = committed_db
    a, b = await make_member(db), await make_member(db)

    def note(member: Member, i: int, *, age_days: int, read: bool) -> Notification:
        at = NOW - timedelta(days=age_days)
        return Notification(recipient_id=member.id, type="t", title_snapshot="t", group_key=f"g{member.id}-{i}",
                            dedupe_key=f"d{member.id}-{i}", created_at=at, read_at=at if read else None)  # fmt: skip

    db.add_all(
        [
            note(a, 1, age_days=91, read=True),  # 읽음 90일 지남 → 삭제
            note(a, 2, age_days=89, read=True),
            note(a, 3, age_days=181, read=False),  # 안 읽음 180일 지남 → 삭제
            note(a, 4, age_days=179, read=False),
            *[note(b, i, age_days=i, read=False) for i in range(5)],  # 최신 3개만 남는다
        ]
    )
    await db.commit()
    async with SessionLocal() as s, s.begin():
        assert await jobs.cleanup_notifications(s) == 4
    left = (await db.execute(select(Notification.dedupe_key).order_by(Notification.dedupe_key))).scalars().all()
    assert left == sorted([f"d{a.id}-2", f"d{a.id}-4", f"d{b.id}-0", f"d{b.id}-1", f"d{b.id}-2"])


async def test_small_cleanups(committed_db: AsyncSession) -> None:
    db = committed_db
    member = await make_member(db)
    board = await make_board(db)
    post = await make_post(db, board, member)
    db.add_all(
        [
            IdempotencyKey(scope="m:1", key="old", request_hash="0" * 64, created_at=NOW - timedelta(hours=25)),
            IdempotencyKey(scope="m:1", key="new", request_hash="0" * 64),
            RateLimitCounter(key="old", window_start=NOW - timedelta(days=2), count=1),
            RateLimitCounter(key="new", window_start=NOW, count=1),
            PostViewDaily(post_id=post.id, viewer_key="g:x", view_date=date.today() - timedelta(days=2)),
            PostViewDaily(post_id=post.id, viewer_key="g:y", view_date=date.today()),
            PostViewOnce(post_id=post.id, viewer_key="g:old", created_at=NOW - timedelta(days=31)),
            PostViewOnce(post_id=post.id, viewer_key=f"m:{member.id}", created_at=NOW - timedelta(days=400)),
            OutboxEvent(type="x", payload={}, processed_at=NOW - timedelta(days=8)),
            OutboxEvent(type="x", payload={}, processed_at=NOW - timedelta(days=1)),
            OutboxEvent(type="x", payload={}, dead_at=NOW - timedelta(days=30)),
        ]
    )
    await db.commit()
    async with SessionLocal() as s, s.begin():
        assert await jobs.cleanup_idempotency(s) == 1
        assert await jobs.cleanup_rate_limits(s) == 1
        assert await jobs.cleanup_view_records(s) == 2
        assert await jobs.cleanup_outbox(s) == 1  # dead 는 운영자가 보도록 남긴다
    assert (await db.execute(select(PostViewOnce.viewer_key))).scalar_one() == f"m:{member.id}"
    assert (await db.execute(select(func.count()).select_from(OutboxEvent))).scalar_one() == 2


async def test_board_daily_stats(committed_db: AsyncSession) -> None:
    db = committed_db
    member = await make_member(db)
    board = await make_board(db, slug="free")
    other = await make_board(db, slug="other")
    today = await make_post(db, board, member)
    await make_post(db, board, member)
    await make_post(db, board, member, published_at=NOW - timedelta(days=3))  # 범위 밖
    await make_post(db, board, member, status="draft")  # 공개 아님
    db.add(Comment(post_id=today.id, member_id=member.id, author_name_snapshot="회원", content="c"))
    db.add(Report(target_type="post", target_id=today.id, board_id=board.id, reason_code="spam"))
    await db.commit()
    async with SessionLocal() as s, s.begin():
        await jobs.aggregate_board_daily_stats(s)
    async with SessionLocal() as s, s.begin():  # 두 번 돌려도 같다(UPSERT)
        await jobs.aggregate_board_daily_stats(s)
    today_d = (await db.execute(select(func.current_date()))).scalar_one()
    rows = {
        (r.board_id, r.day): (r.posts, r.comments, r.reports)
        for r in (await db.execute(select(BoardDailyStat))).scalars()
    }
    assert rows[(board.id, today_d)] == (2, 1, 1)
    assert rows[(other.id, today_d)] == (0, 0, 0)
    assert len(rows) == 4  # 게시판 2 × (오늘, 어제)


# ── 일정 ─────────────────────────────────────────────────


async def test_schedules_run_once_per_interval(committed_db: AsyncSession, monkeypatch) -> None:
    ran = []

    async def fake(_db):
        ran.append(1)
        return 0

    monkeypatch.setattr(jobs, "JOBS", {"test.job": jobs.Job("test.job", 3600, fake)})
    monkeypatch.setattr("app.worker.schedules.JOBS", jobs.JOBS)
    await ensure_schedules()
    assert await run_due_one() == "test.job"  # 처음 만든 작업은 바로 돈다
    assert await run_due_one() is None  # 한 시간 뒤까지 없음
    row = (await committed_db.execute(select(WorkerSchedule).where(WorkerSchedule.name == "test.job"))).scalar_one()
    assert row.locked_until is None and row.last_run_at is not None
    assert timedelta(minutes=59) < row.next_run_at - row.last_run_at <= timedelta(hours=1)
    # 다른 작업자가 잡고 있는(잠금이 살아 있는) 작업은 건너뛴다
    await committed_db.execute(update(WorkerSchedule).values(next_run_at=func.now(), locked_until=func.now() + timedelta(minutes=5)))
    await committed_db.commit()
    assert await run_due_one() is None
    assert ran == [1]


async def test_failing_job_is_rescheduled(committed_db: AsyncSession, monkeypatch) -> None:
    async def broken(_db):
        raise RuntimeError("작업 실패")

    monkeypatch.setattr("app.worker.schedules.JOBS", {"test.broken": jobs.Job("test.broken", 60, broken)})
    await ensure_schedules()
    assert await run_due_one() == "test.broken"
    row = (await committed_db.execute(select(WorkerSchedule).where(WorkerSchedule.name == "test.broken"))).scalar_one()
    assert row.locked_until is None and row.next_run_at > row.last_run_at


# ── 고리: LISTEN 으로 깨어난다 ─────────────────────────────


async def test_listen_wakes_worker(committed_db: AsyncSession, monkeypatch) -> None:
    done = asyncio.Event()

    async def ok(_db, _event):
        done.set()

    monkeypatch.setitem(HANDLERS, "test.ok", ok)
    monkeypatch.setattr("app.worker.schedules.JOBS", {})
    stop = asyncio.Event()
    task = asyncio.create_task(run(stop, poll_seconds=60))  # 폴링으로는 60초 — 빨리 끝나면 LISTEN 덕분
    try:
        await asyncio.sleep(0.5)  # LISTEN 연결이 서도록
        await _enqueue(outbox.Event("test.ok"))
        await asyncio.wait_for(done.wait(), timeout=5)
    finally:
        stop.set()
        await asyncio.wait_for(task, timeout=5)
