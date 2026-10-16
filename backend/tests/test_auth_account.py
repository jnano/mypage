"""내 계정·재확인·기기 목록·탈퇴·강제 탈퇴·재설정 링크 — 인증 설계도 §4.5~§4.9·§4.11·§4.13·§9"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import keys, login as login_service
from app.core import rate_limit
from app.core.rate_limit import Limit
from app.models import (
    Comment,
    LevelRequest,
    LoginSession,
    Member,
    MemberGroup,
    MemberGroupMember,
    MemberSanction,
    ModerationLog,
    OutboxEvent,
    PasswordResetToken,
    Post,
    WithdrawnEmailMark,
)
from tests.factories import TEST_PASSWORD, make_board, make_member, make_post
from tests.test_auth_login import login, whoami

pytestmark = pytest.mark.anyio

NEW = "another sentence long enough"


async def session_of(client, m: Member, ip: str = "203.0.113.10") -> dict[str, str]:
    return {"X-Session": (await login(client, m.email or "", ip=ip)).json()["session_token"]}


async def active(db: AsyncSession, **kw) -> Member:
    m = await make_member(db, **kw)
    await db.commit()
    return m


# ── 비밀번호 변경·재확인(§4.6·§4.13) ────────────────────────


async def test_change_password_keeps_this_session_only(committed_db, client) -> None:
    m = await active(committed_db)
    here = await session_of(client, m)
    there = await session_of(client, m, ip="203.0.113.11")
    r = await client.post("/api/me/password", json={"current_password": TEST_PASSWORD, "new_password": NEW}, headers=here)
    assert r.status_code == 204
    assert await whoami(client, here["X-Session"]) == 200 and await whoami(client, there["X-Session"]) is None
    assert (await login(client, m.email or "", NEW, ip="203.0.113.12")).status_code == 200


async def test_change_password_rules_and_wrong_current(committed_db, client) -> None:
    m = await active(committed_db)
    h = await session_of(client, m)
    r = await client.post("/api/me/password", json={"current_password": "wrong password here", "new_password": NEW}, headers=h)
    assert (r.status_code, r.json()["code"]) == (403, "reauth_failed")
    r = await client.post("/api/me/password", json={"current_password": TEST_PASSWORD, "new_password": "short"}, headers=h)
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "new_password"


async def test_reauth_limited_before_hashing(committed_db, client, monkeypatch) -> None:
    monkeypatch.setitem(rate_limit.LIMITS, "auth.reauth", Limit(2, 900))
    m = await active(committed_db)
    h = await session_of(client, m)
    calls = []
    real = login_service.verify_password
    monkeypatch.setattr(login_service, "verify_password", lambda hsh, p: calls.append(1) or real(hsh, p))
    from app.auth import account as account_module

    monkeypatch.setattr(account_module, "verify_password", lambda hsh, p: calls.append(1) or real(hsh, p))
    codes = [
        (await client.post("/api/me/password", json={"current_password": "wrong password here", "new_password": NEW}, headers=h)).status_code
        for _ in range(3)
    ]
    assert codes == [403, 403, 429] and len(calls) == 2  # 세 번째는 해시를 부르지 않는다


# ── 기기 목록(§4.5) ─────────────────────────────────────────


async def test_sessions_list_and_idor(committed_db, client) -> None:
    m = await active(committed_db)
    other = await active(committed_db)
    here = await session_of(client, m)
    await session_of(client, m, ip="203.0.113.13")
    theirs = await session_of(client, other, ip="203.0.113.14")
    items = (await client.get("/api/me/sessions", headers=here)).json()["items"]
    assert len(items) == 2 and sum(i["current"] for i in items) == 1 and items[0]["user_agent"] == "시험 브라우저"
    their_id = (await client.get("/api/me/sessions", headers=theirs)).json()["items"][0]["id"]
    assert (await client.delete(f"/api/me/sessions/{their_id}", headers=here)).status_code == 404  # 남의 id
    mine = next(i["id"] for i in items if not i["current"])
    assert (await client.delete(f"/api/me/sessions/{mine}", headers=here)).status_code == 204
    assert len((await client.get("/api/me/sessions", headers=here)).json()["items"]) == 1
    assert (await client.get("/api/me/account", headers=here)).json()["email"] == m.email


# ── 탈퇴(§4.9) ──────────────────────────────────────────────


async def test_withdraw_clears_personal_fields_and_authorship(committed_db, client) -> None:
    m = await active(committed_db, level=3)
    board = await make_board(committed_db)
    post = await make_post(committed_db, board, m)
    committed_db.add(Comment(post_id=post.id, member_id=m.id, author_name_snapshot=m.display_name, content="댓글"))
    committed_db.add(LevelRequest(member_id=m.id, from_level=3, to_level=5, reason="활동"))
    group = MemberGroup(name="모임")
    committed_db.add(group)
    await committed_db.flush()
    committed_db.add(MemberGroupMember(group_id=group.id, member_id=m.id))
    committed_db.add(MemberSanction(member_id=m.id, actions=["write"], reason="스팸", ends_at=datetime.now(UTC) + timedelta(days=3)))
    await committed_db.commit()
    email, mid, pid = m.email or "", m.id, post.id
    h = await session_of(client, m)
    assert (await client.post("/api/me/withdraw", json={"password": "wrong password here"}, headers=h)).status_code == 403
    assert (await client.post("/api/me/withdraw", json={"password": TEST_PASSWORD}, headers=h)).status_code == 204
    committed_db.expire_all()
    gone = await committed_db.get(Member, mid)
    assert (gone.status, gone.display_name, gone.email, gone.password_hash, gone.display_name_key) == ("withdrawn", "탈퇴 회원", None, None, None)
    p = await committed_db.get(Post, pid)
    assert (p.member_id, p.author_name_snapshot) == (None, "탈퇴 회원")
    c = (await committed_db.execute(select(Comment).where(Comment.post_id == pid))).scalar_one()
    assert (c.member_id, c.author_name_snapshot) == (None, "탈퇴 회원")
    assert (await committed_db.execute(select(LevelRequest.status))).scalar_one() == "cancelled"
    assert (await committed_db.execute(select(MemberGroupMember))).first() is None  # 그룹 소속도 지운다
    assert await whoami(client, h["X-Session"]) is None
    # 제재 중 탈퇴 → 주소 HMAC 표시(90일), 캐시 무효화 예약
    mark = (await committed_db.execute(select(WithdrawnEmailMark))).scalar_one()
    assert mark.email_hmac == keys.email_hmac(email)
    event = (await committed_db.execute(select(OutboxEvent).where(OutboxEvent.type == "cache.revalidate"))).scalar_one()
    assert f"post:{pid}" in event.payload["max"]
    # 같은 이메일 로그인은 없는 이메일과 같은 실패
    assert (await login(client, email, TEST_PASSWORD)).json()["code"] == "login_failed"


async def test_last_admin_cannot_withdraw_and_concurrent_admins(committed_db, client) -> None:
    a = await active(committed_db, is_admin=True)
    ha = await session_of(client, a)
    r = await client.post("/api/me/withdraw", json={"password": TEST_PASSWORD}, headers=ha)
    assert (r.status_code, r.json()["code"]) == (409, "last_admin")
    b = await active(committed_db, is_admin=True)
    hb = await session_of(client, b, ip="203.0.113.15")
    results = await asyncio.gather(
        client.post("/api/me/withdraw", json={"password": TEST_PASSWORD}, headers=ha),
        client.post("/api/me/withdraw", json={"password": TEST_PASSWORD}, headers=hb),
    )
    assert sorted(r.status_code for r in results) == [204, 409]  # 한 명은 남는다, 교착 없음


async def test_forced_withdraw(committed_db, client) -> None:
    admin = await active(committed_db, is_admin=True)
    other_admin = await active(committed_db, is_admin=True)
    target = await active(committed_db)
    h = await session_of(client, admin)
    url = f"/api/admin/members/{target.id}/withdraw"
    assert (await client.post(url, json={"password": TEST_PASSWORD}, headers=h)).status_code == 422  # 사유 필수
    assert (await client.post(url, json={"password": TEST_PASSWORD, "reason": "   "}, headers=h)).status_code == 422  # 공백만
    r = await client.post(url, json={"password": "wrong password here", "reason": "규칙 위반"}, headers=h)
    assert r.status_code == 403
    failed = (await committed_db.execute(select(ModerationLog).where(ModerationLog.action == "member.reauth_failed"))).scalar_one()
    assert failed.actor_id == admin.id  # 본 요청이 되돌려져도 남는다
    r = await client.post(f"/api/admin/members/{other_admin.id}/withdraw", json={"password": TEST_PASSWORD, "reason": "x"}, headers=h)
    assert (r.status_code, r.json()["code"]) == (403, "target_is_admin")
    assert (await client.post(url, json={"password": TEST_PASSWORD, "reason": "규칙 위반"}, headers=h)).status_code == 204
    log = (await committed_db.execute(select(ModerationLog).where(ModerationLog.action == "member.withdraw"))).scalar_one()
    assert log.reason == "규칙 위반" and log.before["email"].endswith("***.test")


# ── 재설정 링크(§4.8) ───────────────────────────────────────


async def test_reset_link_flow(committed_db, client) -> None:
    admin = await active(committed_db, is_admin=True)
    target = await active(committed_db)
    email = target.email or ""
    h = await session_of(client, admin)
    their = await session_of(client, target, ip="203.0.113.16")
    url = f"/api/admin/members/{target.id}/password-reset-link"
    first = (await client.post(url, json={"password": TEST_PASSWORD}, headers=h)).json()
    second = (await client.post(url, json={"password": TEST_PASSWORD}, headers=h)).json()
    assert second["path"].startswith("/reset#t=")
    old_token, token = first["path"].split("#t=")[1], second["path"].split("#t=")[1]

    def reset(t: str, pw: str = NEW):
        return client.post("/api/auth/password-reset", json={"token": t, "password": pw}, headers={"X-Client-IP": "198.51.100.5"})

    assert (await reset(old_token)).status_code == 410  # 새 링크가 옛 링크를 막는다
    assert (await reset(token, "short")).status_code == 422
    assert (await reset(token)).status_code == 204
    assert (await reset(token)).status_code == 410  # 한 번만
    assert await whoami(client, their["X-Session"]) is None  # 세션 전부 폐기
    first_login = (await login(client, email, NEW, ip="203.0.113.17")).json()
    assert first_login["notices"] == ["password_reset_by_admin"]
    assert (await login(client, email, NEW, ip="203.0.113.18")).json()["notices"] == []


async def test_reset_link_guards(committed_db, client) -> None:
    admin = await active(committed_db, is_admin=True)
    other_admin = await active(committed_db, is_admin=True)
    target = await active(committed_db)
    h = await session_of(client, admin)
    r = await client.post(f"/api/admin/members/{other_admin.id}/password-reset-link", json={"password": TEST_PASSWORD}, headers=h)
    assert (r.status_code, r.json()["code"]) == (403, "target_is_admin")
    path = (await client.post(f"/api/admin/members/{target.id}/password-reset-link", json={"password": TEST_PASSWORD}, headers=h)).json()["path"]
    await committed_db.execute(update(PasswordResetToken).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
    await committed_db.commit()
    r = await client.post("/api/auth/password-reset", json={"token": path.split("#t=")[1], "password": NEW})
    assert r.status_code == 410  # 24시간 지남
    member = await active(committed_db)
    mh = await session_of(client, member, ip="203.0.113.19")
    assert (await client.post(f"/api/admin/members/{target.id}/password-reset-link", json={"password": TEST_PASSWORD}, headers=mh)).status_code == 403
    assert (await committed_db.execute(select(LoginSession.id))).first() is not None
