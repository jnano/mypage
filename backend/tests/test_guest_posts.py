"""비회원 글쓰기 — 설계도 §6.3. 작성 순서·보안 문자·비회원 토큰·수정/삭제·IP 해시·정리·검색 제한."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import rate_limit
from app.core.rate_limit import Limit
from app.db.session import SessionLocal
from app.models import BoardModerator, ModerationLog, Notification, Post, SiteSetting, UsedNonce
from app.posts import guest
from app.worker import handlers, jobs
from tests.factories import make_board, make_member, make_post
from tests.helpers import as_member

pytestmark = pytest.mark.anyio

IP = "203.0.113.40"


async def _board(db: AsyncSession, *, approval: bool = True, **kw):
    board = await make_board(
        db, slug="open", write_level=0, spam_policy={"min_elapsed_sec": 0, "guest_requires_approval": approval}, **kw
    )
    await db.commit()
    return board


def _answer(captcha_token: str) -> str:
    x, y = guest._numbers(captcha_token.split(".")[0])
    return str(x + y)


async def _form(client: AsyncClient, slug: str = "open") -> dict:
    res = await client.get(f"/api/boards/{slug}/guest-form")
    assert res.status_code == 200, res.text
    assert res.headers["cache-control"] == "no-store"
    return res.json()


async def _write(client: AsyncClient, *, ip: str = IP, slug: str = "open", **over) -> dict:
    form = await _form(client, slug)
    body = {
        "title": "모집 안내",
        "content": "<p>함께할 분을 찾습니다</p>",
        "author_name": "손님",
        "password": "garden-key",
        "form_token": form["form_token"],
        "captcha_token": form["captcha"]["token"],
        "captcha_answer": _answer(form["captcha"]["token"]),
    } | over
    return await client.post(f"/api/boards/{slug}/posts", json=body, headers={"X-Client-IP": ip})


# ── 작성 ─────────────────────────────────────────────────


async def test_guest_post_pending_with_token_and_ip_hash(committed_db, client) -> None:
    board = await _board(committed_db)
    mod = await make_member(committed_db, level=1)
    committed_db.add(BoardModerator(board_id=board.id, member_id=mod.id))
    await committed_db.commit()
    form = await _form(client)
    assert form["captcha"]["question"].endswith("더하기 " + form["captcha"]["question"].split("더하기 ")[1])
    assert form["policy"] == {"honeypot": True, "min_elapsed_sec": 0}
    res = await _write(client)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["post"]["status"] == "pending" and body["guest_token"]
    row = (await committed_db.execute(select(Post).where(Post.id == body["post"]["id"]))).scalar_one()  # post-clause: exempt — 시험
    assert (row.is_guest, row.member_id, row.author_name_snapshot, row.status, row.published_at) == (True, None, "손님", "pending", None)
    assert len(row.ip_hash) == 64 and row.ip_hash_period == guest.ip_period()
    assert row.ip_hash == guest.ip_hash(IP, row.ip_hash_period) and IP not in row.ip_hash
    # 담당자 알림(작업자가 처리)
    async with SessionLocal() as s, s.begin():
        from app.models import OutboxEvent

        ev = (await s.execute(select(OutboxEvent).where(OutboxEvent.type == "post.created"))).scalar_one()
        await handlers.post_created(s, ev)
    notes = (await committed_db.execute(select(Notification.type, Notification.recipient_id))).all()
    assert ("admin.guest_pending", mod.id) in notes


async def test_published_when_no_approval(committed_db, client) -> None:
    await _board(committed_db, approval=False)
    res = await _write(client)
    assert res.status_code == 201 and res.json()["post"]["status"] == "published"
    page = await client.get(f"/api/posts/{res.json()['post']['id']}/page")
    assert page.status_code == 200 and page.json()["post"]["author_is_guest"] is True


async def test_rejections(dev_header, committed_db, client) -> None:
    await _board(committed_db)
    closed = await make_board(committed_db, slug="members")  # write_level 1
    member = await make_member(committed_db, level=1, display_name="이미있는회원")
    await committed_db.commit()
    assert (await client.get("/api/boards/members/guest-form")).status_code == 403
    assert (await client.get("/api/boards/open/guest-form", headers=as_member(member.id))).status_code == 409
    cases = [
        ({"website": "http://spam"}, "form_rejected"),  # 숨은 칸
        ({"form_token": "x.y.z"}, "form_rejected"),
        ({"captcha_token": "bad"}, "form_rejected"),
        ({"captcha_answer": "999"}, "captcha_wrong"),
        ({"attachments": [{"id": 1}]}, "validation_error"),
        ({"author_name": "운영자"}, "validation_error"),  # 쓸 수 없는 이름
        ({"author_name": "이미 있는 회원"}, "validation_error"),  # 회원 사칭(정규화 키)
        ({"password": "12345"}, "validation_error"),  # 6자 미만
        ({"is_secret": True}, "validation_error"),  # 비밀글 안 되는 게시판
    ]
    for over, code in cases:
        res = await _write(client, **over)
        assert res.status_code == 422 and res.json()["code"] == code, (over, res.text)
    assert closed.write_level == 1


async def test_captcha_is_one_time_even_when_wrong(committed_db, client) -> None:
    await _board(committed_db)
    form = await _form(client)
    base = {"title": "제목", "content": "<p>본문</p>", "author_name": "손님", "password": "garden-key", "form_token": form["form_token"], "captcha_token": form["captcha"]["token"]}
    wrong = await client.post("/api/boards/open/posts", json=base | {"captcha_answer": "0"}, headers={"X-Client-IP": IP})
    assert wrong.json()["code"] == "captcha_wrong"
    right = await client.post("/api/boards/open/posts", json=base | {"captcha_answer": _answer(form["captcha"]["token"])}, headers={"X-Client-IP": IP})
    assert right.status_code == 422 and right.json()["code"] == "form_rejected"  # 같은 문제를 다시 맞혀 보지 못한다
    assert (await committed_db.execute(select(func.count()).select_from(UsedNonce))).scalar_one() == 1


async def test_attempt_limit_counts_failures(committed_db, client, monkeypatch) -> None:
    await _board(committed_db)
    monkeypatch.setitem(rate_limit.LIMITS, "post.create_guest_attempt", Limit(3, 600))
    for _ in range(3):
        assert (await _write(client, captcha_answer="0")).status_code == 422
    assert (await _write(client)).status_code == 429  # 실패 제출도 센다 — 맞는 답도 막힌다


async def test_success_limit_and_site_alert(committed_db, client, monkeypatch) -> None:
    await _board(committed_db)
    monkeypatch.setitem(rate_limit.LIMITS, "post.create_guest_all", Limit(1, 3600))
    assert (await _write(client, ip="198.51.100.1")).status_code == 201
    assert (await _write(client, ip="198.51.100.2")).status_code == 429
    assert (await _write(client, ip="198.51.100.3")).status_code == 429
    alerts = (await committed_db.execute(select(func.count()).select_from(ModerationLog).where(ModerationLog.action == "alert.guest_posts"))).scalar_one()
    assert alerts == 1  # 처음 넘는 순간 한 줄


# ── 비회원 토큰 ──────────────────────────────────────────


async def test_token_same_failure_for_every_case(committed_db, client) -> None:
    board = await _board(committed_db, approval=False)
    member = await make_member(committed_db, level=1)
    member_post = await make_post(committed_db, board, member)
    await committed_db.commit()
    pid = (await _write(client)).json()["post"]["id"]
    ok = await client.post(f"/api/posts/{pid}/guest-token", json={"password": "garden-key", "purpose": "edit"}, headers={"X-Client-IP": IP})
    assert ok.status_code == 200 and ok.json()["purpose"] == "edit" and ok.headers["cache-control"] == "no-store"
    bodies = []
    for target, pw in ((pid, "wrong-pass"), (999999, "garden-key"), (member_post.id, "garden-key")):
        res = await client.post(f"/api/posts/{target}/guest-token", json={"password": pw, "purpose": "read"}, headers={"X-Client-IP": "198.51.100.9"})
        assert res.status_code == 401
        bodies.append(res.json())
    assert bodies[0] == bodies[1] == bodies[2]  # 가르지 않는다


async def test_token_attempt_limits(committed_db, client, monkeypatch) -> None:
    await _board(committed_db, approval=False)
    pid = (await _write(client)).json()["post"]["id"]
    monkeypatch.setitem(rate_limit.LIMITS, "guest.token", Limit(2, 600))
    monkeypatch.setitem(rate_limit.LIMITS, "guest.token_post", Limit(2, 600))
    send = lambda ip: client.post(f"/api/posts/{pid}/guest-token", json={"password": "x" * 8, "purpose": "read"}, headers={"X-Client-IP": ip})  # noqa: E731
    assert [(await send("198.51.100.1")).status_code for _ in range(3)] == [401, 401, 429]  # IP·글
    assert (await send("198.51.100.2")).status_code == 429  # 글 전체(2)를 넘음 — 다른 IP 도(ip1 의 셋째는 IP 한도에서 먼저 멈춰 글 몫을 세지 않았다)


def _tok(client: AsyncClient, token: str) -> dict:
    return {"X-Guest-Token": token, "X-Client-IP": IP}


async def test_token_opens_pending_and_secret_posts(committed_db, client, browser) -> None:
    await _board(committed_db, allow_secret=True)
    created = (await _write(client, is_secret=True)).json()
    pid, token = created["post"]["id"], created["guest_token"]
    assert (await client.get(f"/api/posts/{pid}/page")).status_code == 404  # 대기 글은 있음을 드러내지 않는다
    page = await client.get(f"/api/posts/{pid}/page", headers=_tok(client, token))
    assert page.status_code == 200 and page.json()["guest_can_edit"] is True
    # 내부 비밀이 없으면 머리를 믿지 않는다(쓰기 경계와 별개로 읽기도)
    assert (await browser.get(f"/api/posts/{pid}/page", headers={"X-Guest-Token": token})).status_code == 404
    # 서명이 틀리거나 다른 글의 토큰은 무시
    assert (await client.get(f"/api/posts/{pid}/page", headers=_tok(client, token[:-2] + "xx"))).status_code == 404
    other = guest.sign_token(pid + 1, "edit")
    assert (await client.get(f"/api/posts/{pid}/page", headers=_tok(client, other))).status_code == 404


# ── 수정·삭제 ────────────────────────────────────────────


async def _approve(client: AsyncClient, pid: int, admin_id: int):
    return await client.post(f"/api/posts/{pid}/approve", json={}, headers=as_member(admin_id))


async def test_edit_repends_and_keeps_first_published_at(dev_header, committed_db, client) -> None:
    await _board(committed_db)
    admin = await make_member(committed_db, level=9, is_admin=True)
    await committed_db.commit()
    admin_id = admin.id
    created = (await _write(client)).json()
    pid, token = created["post"]["id"], created["guest_token"]
    assert (await _approve(client, pid, admin_id)).status_code == 200
    first = (await committed_db.execute(select(Post.published_at).where(Post.id == pid))).scalar_one()  # post-clause: exempt — 시험
    edit = await client.get(f"/api/posts/{pid}", headers=_tok(client, token))
    assert edit.status_code == 200
    # 수정 화면은 첨부가 없어도 attachments: [] 를 보낸다 — 받아야 한다
    res = await client.patch(f"/api/posts/{pid}", json={"title": "고친 제목", "attachments": []}, headers=_tok(client, token) | {"If-Match": f'"{edit.json()["version"]}"'})
    assert res.status_code == 200, res.text
    assert f"board:open" in res.json()["invalidate"]["now"]  # 공개 글이 비공개가 됐다
    committed_db.expire_all()
    row = (await committed_db.execute(select(Post.status, Post.published_at).where(Post.id == pid))).one()  # post-clause: exempt — 시험
    assert row.status == "pending" and row.published_at == first
    assert (await _approve(client, pid, admin_id)).status_code == 200
    committed_db.expire_all()
    assert (await committed_db.execute(select(Post.published_at).where(Post.id == pid))).scalar_one() == first  # post-clause: exempt — 시험
    # 이름·관리 칸은 못 고친다, read 토큰으로는 수정 403
    v = (await client.get(f"/api/posts/{pid}", headers=_tok(client, token))).json()["version"]
    assert (await client.patch(f"/api/posts/{pid}", json={"is_pinned": True}, headers=_tok(client, token) | {"If-Match": f'"{v}"'})).status_code == 422
    assert (await client.patch(f"/api/posts/{pid}", json={"attachments": [{"id": 1}]}, headers=_tok(client, token) | {"If-Match": f'"{v}"'})).status_code == 422
    read = guest.sign_token(pid, "read")
    assert (await client.patch(f"/api/posts/{pid}", json={"title": "x"}, headers=_tok(client, read) | {"If-Match": f'"{v}"'})).status_code == 403


async def test_guest_trash_with_edit_token_only(committed_db, client) -> None:
    await _board(committed_db, approval=False)
    created = (await _write(client)).json()
    pid, token = created["post"]["id"], created["guest_token"]
    assert (await client.delete(f"/api/posts/{pid}")).status_code == 401
    assert (await client.delete(f"/api/posts/{pid}", headers=_tok(client, guest.sign_token(pid, "read")))).status_code == 401
    res = await client.delete(f"/api/posts/{pid}", headers=_tok(client, token))
    assert res.status_code == 200, res.text
    committed_db.expire_all()
    assert (await committed_db.execute(select(Post.status).where(Post.id == pid))).scalar_one() == "trashed"  # post-clause: exempt — 시험
    # 휴지통 글로는 토큰을 받지 못한다
    again = await client.post(f"/api/posts/{pid}/guest-token", json={"password": "garden-key", "purpose": "edit"}, headers={"X-Client-IP": "198.51.100.30"})
    assert again.status_code == 401


# ── 정리·검색 ────────────────────────────────────────────


async def test_cleanups(committed_db, client) -> None:
    await _board(committed_db)
    old = (await _write(client, ip="198.51.100.50")).json()["post"]["id"]
    keep = (await _write(client, ip="198.51.100.51")).json()["post"]["id"]
    await committed_db.execute(update(Post).where(Post.id == old).values(created_at=datetime.now(UTC) - timedelta(days=31), ip_hash_period=guest.ip_period() - 2))  # post-clause: exempt — 시험
    committed_db.add(UsedNonce(nonce="n" * 22, expires_at=datetime.now(UTC) - timedelta(minutes=1)))
    await committed_db.commit()
    before = (await committed_db.execute(select(Post.updated_at).where(Post.id == old))).scalar_one()  # post-clause: exempt — 시험
    async with SessionLocal() as s, s.begin():
        assert await jobs.cleanup_guest_ip_hash(s) == 1
        assert await jobs.trash_stale_guest_pending(s) == 1
        assert await jobs.cleanup_used_nonces(s) == 1
    committed_db.expire_all()
    rows = {r.id: r for r in await committed_db.execute(select(Post.id, Post.status, Post.ip_hash, Post.updated_at).where(Post.id.in_([old, keep])))}  # post-clause: exempt — 시험
    assert rows[old].ip_hash is None and rows[keep].ip_hash is not None
    assert rows[old].status == "trashed" and rows[keep].status == "pending"
    log = (await committed_db.execute(select(ModerationLog).where(ModerationLog.action == "post.auto_trash"))).scalar_one()
    assert log.actor_id is None and log.target_id == old
    assert before is not None


async def test_guest_search_is_rate_limited_per_ip(committed_db, client, monkeypatch) -> None:
    monkeypatch.setitem(rate_limit.LIMITS, "search", Limit(1, 60))
    assert (await client.get("/api/search", params={"q": "회의"}, headers={"X-Client-IP": "198.51.100.60"})).status_code == 200
    assert (await client.get("/api/search", params={"q": "회의"}, headers={"X-Client-IP": "198.51.100.61"})).status_code == 200
    assert (await client.get("/api/search", params={"q": "회의"}, headers={"X-Client-IP": "198.51.100.60"})).status_code == 429
    assert SiteSetting is not None
