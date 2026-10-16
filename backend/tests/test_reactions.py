"""글 반응 — 설계도 §6.1. 추천·스크랩(상태 지정)·조회수(once·daily·always)·공유."""

import asyncio
import secrets
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import rate_limit
from app.core.config import settings
from app.core.rate_limit import Limit
from app.db.session import SessionLocal
from app.models import MemberSanction, Post, PostStat, PostViewDaily, PostViewOnce, RateLimitCounter
from app.posts import reactions, view_buffer
from tests.factories import make_board, make_member, make_post
from tests.helpers import as_member

pytestmark = pytest.mark.anyio


async def _world(db: AsyncSession, **board_kw):
    author = await make_member(db, level=1, display_name="글쓴이")
    reader = await make_member(db, level=1, display_name="읽는이")
    board = await make_board(db, slug="free", **board_kw)
    post = await make_post(db, board, author)
    db.add(PostStat(post_id=post.id))
    await db.commit()
    return author, reader, board, post


async def _stat(_db: AsyncSession, post_id: int):
    async with SessionLocal() as s:  # 앱이 커밋한 값을 새 세션으로
        return (await s.execute(select(PostStat.view_count, PostStat.like_count, PostStat.scrap_count, PostStat.share_count).where(PostStat.post_id == post_id))).one()


def _token() -> str:
    return secrets.token_urlsafe(32)  # 43자 — Route Handler 가 만드는 값과 같은 꼴


async def _view(client: AsyncClient, post_id: int, *, token: str | None = None, ip: str = "203.0.113.1", member: int | None = None):
    headers = {"X-Client-IP": ip}
    if token is not None:
        headers["X-View-Token"] = token
    if member is not None:
        headers |= as_member(member)
    return await client.post(f"/api/posts/{post_id}/view", headers=headers)


# ── 추천·스크랩 ─────────────────────────────────────────


@pytest.mark.parametrize(("kind", "state", "count_key", "column"), [("like", "liked", "like_count", "like_count"), ("scrap", "scrapped", "scrap_count", "scrap_count")])
async def test_state_setting_is_idempotent(dev_header, committed_db, client, kind, state, count_key, column) -> None:
    _, reader, _, post = await _world(committed_db)
    h = as_member(reader.id)
    for _ in range(2):
        res = await client.put(f"/api/posts/{post.id}/{kind}", headers=h)
        assert res.status_code == 200 and res.json() == {state: True, count_key: 1}
        assert res.headers["cache-control"] == "no-store"
    assert getattr(await _stat(committed_db, post.id), column) == 1
    for _ in range(2):
        res = await client.delete(f"/api/posts/{post.id}/{kind}", headers=h)
        assert res.json() == {state: False, count_key: 0}
    assert getattr(await _stat(committed_db, post.id), column) == 0


async def test_concurrent_turn_on_counts_once(dev_header, committed_db, client) -> None:
    _, reader, _, post = await _world(committed_db)
    results = await asyncio.gather(*(client.put(f"/api/posts/{post.id}/like", headers=as_member(reader.id)) for _ in range(5)))
    assert all(r.status_code == 200 for r in results)
    assert (await _stat(committed_db, post.id)).like_count == 1  # 최종 판정은 PK


async def test_turn_on_rules(dev_header, committed_db, client) -> None:
    author, reader, board, post = await _world(committed_db)
    assert (await client.put(f"/api/posts/{post.id}/like")).status_code == 401
    assert (await client.put("/api/posts/999999/like", headers=as_member(reader.id))).status_code == 404
    secret = await make_post(committed_db, board, author, is_secret=True)
    pending = await make_post(committed_db, board, author, status="pending")
    committed_db.add_all([PostStat(post_id=secret.id), PostStat(post_id=pending.id)])
    # 정지는 막지 않는다(§6.1) — 쓰기·댓글·업로드 정지 모두
    committed_db.add(MemberSanction(member_id=reader.id, actions=["write", "comment", "upload"], reason="시험", ends_at=datetime.now(UTC) + timedelta(days=1)))
    await committed_db.commit()
    # 읽을 수 없는 글은 있음을 드러내지 않는다
    res = await client.put(f"/api/posts/{secret.id}/like", headers=as_member(reader.id))
    assert res.status_code == 404 and res.json()["code"] == "post_not_found"
    # 작성자는 대기 글을 읽을 수 있지만 공개 글이 아니다
    res = await client.put(f"/api/posts/{pending.id}/like", headers=as_member(author.id))
    assert res.status_code == 409 and res.json()["code"] == "not_published"
    assert (await client.put(f"/api/posts/{post.id}/like", headers=as_member(reader.id))).status_code == 200
    # 자기 글 추천 허용
    assert (await client.put(f"/api/posts/{post.id}/like", headers=as_member(author.id))).json()["like_count"] == 2


async def test_turn_off_on_unreadable_post_hides_count(dev_header, committed_db, client) -> None:
    _, reader, _, post = await _world(committed_db)
    h = as_member(reader.id)
    await client.put(f"/api/posts/{post.id}/scrap", headers=h)
    await committed_db.execute(update(Post).where(Post.id == post.id).values(is_secret=True))  # post-clause: exempt — 시험
    await committed_db.commit()
    res = await client.delete(f"/api/posts/{post.id}/scrap", headers=h)
    assert res.status_code == 200 and res.json() == {"scrapped": False}  # 수를 싣지 않는다
    assert (await _stat(committed_db, post.id)).scrap_count == 0
    # 없는 글도 멱등 — '내 스크랩'에서 지워진 글을 정리하는 경로
    assert (await client.delete("/api/posts/999999/scrap", headers=h)).json() == {"scrapped": False}
    assert (await client.delete(f"/api/posts/{post.id}/scrap")).status_code == 401


async def test_react_rate_limit(dev_header, committed_db, client, monkeypatch, caplog) -> None:
    _, reader, _, post = await _world(committed_db)
    monkeypatch.setitem(rate_limit.LIMITS, "post.react", Limit(2, 60))
    h = as_member(reader.id)
    assert (await client.put(f"/api/posts/{post.id}/like", headers=h)).status_code == 200
    assert (await client.delete(f"/api/posts/{post.id}/like", headers=h)).status_code == 200
    with caplog.at_level("WARNING"):
        for _ in range(2):
            res = await client.put(f"/api/posts/{post.id}/like", headers=h)
            assert res.status_code == 429 and "retry-after" in res.headers
    warned = [r for r in caplog.records if "post.react" in r.getMessage()]
    assert len(warned) == 1  # 창마다 처음 넘는 순간 한 번
    assert f"m:{reader.id}" not in warned[0].getMessage()  # 주체 원문을 싣지 않는다


async def test_page_state_reports_reactions(dev_header, committed_db, client) -> None:
    author, reader, board, post = await _world(committed_db)
    other = await make_post(committed_db, board, author)
    committed_db.add(PostStat(post_id=other.id))
    await committed_db.commit()
    h = as_member(reader.id)
    await client.put(f"/api/posts/{post.id}/like", headers=h)
    await client.put(f"/api/posts/{other.id}/scrap", headers=h)
    body = (await client.get(f"/api/me/page-state?board=free&ids={post.id},{other.id}", headers=h)).json()
    assert (body["liked"], body["scrapped"]) == ([post.id], [other.id])
    body = (await client.get(f"/api/me/page-state?board=free&ids={post.id},{other.id}", headers=as_member(author.id))).json()
    assert (body["liked"], body["scrapped"]) == ([], [])


# ── 조회수 ───────────────────────────────────────────────


def test_viewer_key_shape() -> None:
    from app.auth.viewer import GUEST, Viewer

    token = _token()
    key = reactions.viewer_key(GUEST, token)
    assert key is not None and key.startswith("g:") and len(key) == 45  # varchar(64) 안
    assert reactions.viewer_key(GUEST, token) == key
    assert reactions.viewer_key(GUEST, _token()) != key
    assert reactions.viewer_key(GUEST, None) is None
    assert reactions.viewer_key(GUEST, "짧음") is None
    assert reactions.viewer_key(GUEST, token[:-1] + "=") is None
    assert reactions.viewer_key(Viewer(member_id=7, level=1), None) == "m:7"


async def test_once_mode(dev_header, committed_db, client) -> None:
    _, reader, _, post = await _world(committed_db, view_count_mode="once")
    a, b = _token(), _token()
    for _ in range(2):
        assert (await _view(client, post.id, token=a)).status_code == 204
    await _view(client, post.id, token=b)  # 다른 조회 쿠키 — 따로 센다
    await _view(client, post.id, member=reader.id)
    await _view(client, post.id, member=reader.id)
    assert (await _stat(committed_db, post.id)).view_count == 3
    keys = set((await committed_db.execute(select(PostViewOnce.viewer_key))).scalars())
    assert f"m:{reader.id}" in keys and sum(k.startswith("g:") for k in keys) == 2


async def test_daily_mode_uses_site_date(dev_header, committed_db, client) -> None:
    _, _, _, post = await _world(committed_db, view_count_mode="daily")
    token = _token()
    await _view(client, post.id, token=token)
    await _view(client, post.id, token=token)
    assert (await _stat(committed_db, post.id)).view_count == 1
    day = (await committed_db.execute(select(PostViewDaily.view_date))).scalar_one()
    assert day == datetime.now(ZoneInfo(settings.site_time_zone)).date()  # DB 세션 시간대가 아니다
    # 날짜가 바뀐 것처럼 — 어제 기록이면 오늘 다시 센다
    await committed_db.execute(update(PostViewDaily).values(view_date=day - timedelta(days=1)))
    await committed_db.commit()
    await _view(client, post.id, token=token)
    assert (await _stat(committed_db, post.id)).view_count == 2


async def test_always_mode_buffers_then_flushes(dev_header, committed_db, client) -> None:
    _, _, _, post = await _world(committed_db, view_count_mode="always")
    view_buffer._pending.clear()
    token = _token()
    for _ in range(3):
        await _view(client, post.id, token=token)
    assert (await _stat(committed_db, post.id)).view_count == 0  # 행을 갱신하지 않는다
    assert view_buffer.pending() == {post.id: 3}
    view_buffer.add(post.id)  # 다른 프로세스 몫처럼 더해도 합계
    view_buffer.add(999999)  # 지워진 글은 0행 갱신으로 버려진다
    assert await view_buffer.flush() == 2
    assert (await _stat(committed_db, post.id)).view_count == 4
    assert view_buffer.pending() == {}


async def test_flush_failure_requeues_then_drops(monkeypatch, caplog) -> None:
    view_buffer._pending.clear()
    view_buffer.add(1)

    class Broken:
        def __call__(self):
            raise ConnectionError("DB 없음")

    monkeypatch.setattr(view_buffer, "SessionLocal", Broken())
    assert await view_buffer.flush() == 0
    assert view_buffer.pending() == {1: 1}  # 되돌림
    assert await view_buffer.flush() == 0
    assert view_buffer.pending() == {1: 1}
    with caplog.at_level("WARNING"):
        assert await view_buffer.flush() == 0
    assert view_buffer.pending() == {}  # 3번째에 버림
    assert any("버립니다" in r.getMessage() for r in caplog.records)


async def test_view_not_counted_without_permission_or_key(dev_header, committed_db, client, browser) -> None:
    author, _, board, post = await _world(committed_db, view_count_mode="once")
    secret = await make_post(committed_db, board, author, is_secret=True)
    committed_db.add(PostStat(post_id=secret.id))
    await committed_db.commit()
    assert (await _view(client, secret.id, token=_token())).status_code == 204  # 세지 않아도 204
    assert (await _view(client, 999999, token=_token())).status_code == 204
    assert (await _view(client, post.id)).status_code == 204  # 비회원인데 조회 쿠키가 없음
    assert (await _view(client, post.id, token="not-a-view-token")).status_code == 204
    assert (await _stat(committed_db, secret.id)).view_count == 0
    assert (await _stat(committed_db, post.id)).view_count == 0
    # 내부 비밀이 없으면 쓰기 경계에서 막힌다 — X-View-Token 을 바로 믿는 길이 없다
    res = await browser.post(f"/api/posts/{post.id}/view", headers={"X-View-Token": _token()})
    assert res.status_code == 403


async def test_view_rate_limit_is_per_client_ip(dev_header, committed_db, client, monkeypatch) -> None:
    _, _, _, post = await _world(committed_db, view_count_mode="once")
    monkeypatch.setitem(rate_limit.LIMITS, "post.view", Limit(1, 60))
    assert (await _view(client, post.id, token=_token(), ip="198.51.100.1")).status_code == 204
    assert (await _view(client, post.id, token=_token(), ip="198.51.100.2")).status_code == 204  # 다른 사람
    assert (await _view(client, post.id, token=_token(), ip="198.51.100.1")).status_code == 429
    assert (await _stat(committed_db, post.id)).view_count == 2
    keys = set((await committed_db.execute(select(RateLimitCounter.key))).scalars())
    assert {"post.view:198.51.100.1", "post.view:198.51.100.2"} <= keys


# ── 공유 ─────────────────────────────────────────────────


async def test_share_counts_with_hourly_cap(dev_header, committed_db, client) -> None:
    _, _, _, post = await _world(committed_db)
    for _ in range(4):
        assert (await client.post(f"/api/posts/{post.id}/share", headers={"X-Client-IP": "203.0.113.9"})).status_code == 204
    assert (await _stat(committed_db, post.id)).share_count == 3  # IP·글 시간당 3
    await client.post(f"/api/posts/{post.id}/share", headers={"X-Client-IP": "203.0.113.10"})
    assert (await _stat(committed_db, post.id)).share_count == 4


async def test_share_off_board_does_not_count(dev_header, committed_db, client) -> None:
    _, _, _, post = await _world(committed_db, allow_share=False)
    assert (await client.post(f"/api/posts/{post.id}/share")).status_code == 204
    assert (await _stat(committed_db, post.id)).share_count == 0


async def test_flush_runs_against_real_session_factory() -> None:
    assert view_buffer.SessionLocal is SessionLocal
