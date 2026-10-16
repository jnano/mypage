"""회원 관리·그룹(운영자) — 인증 설계도 §4.7·§4.10-5·§4.11·§4.13·§9('마지막 운영자'·'만료'·'운영자 보호')"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BoardAccess, LevelRequest, LoginSession, Member, ModerationLog, OutboxEvent
from tests.factories import TEST_PASSWORD, make_board, make_member
from tests.test_auth_login import login, whoami

pytestmark = pytest.mark.anyio


async def active(db: AsyncSession, **kw) -> Member:
    m = await make_member(db, **kw)
    await db.commit()
    return m


async def session_of(client, m: Member, ip: str = "203.0.113.40", persistent: bool = False) -> dict[str, str]:
    return {"X-Session": (await login(client, m.email or "", ip=ip, persistent=persistent)).json()["session_token"]}


async def admin_headers(db, client) -> tuple[Member, dict[str, str]]:
    admin = await active(db, is_admin=True, display_name="운영자")
    return admin, await session_of(client, admin)


# ── 목록·상세 ───────────────────────────────────────────────


async def test_list_search_and_cursor(committed_db, client, monkeypatch) -> None:
    from app.auth import member_admin

    monkeypatch.setattr(member_admin, "PAGE", 2)
    _, h = await admin_headers(committed_db, client)
    for name in ("회의 담당", "모집 담당", "자유 회원"):
        await active(committed_db, display_name=name)
    first = (await client.get("/api/admin/members?status=active", headers=h)).json()
    assert len(first["items"]) == 2 and first["next_after"]
    rest = (await client.get(f"/api/admin/members?status=active&after={first['next_after']}", headers=h)).json()
    assert len(rest["items"]) == 2 and rest["next_after"] is None
    found = (await client.get("/api/admin/members?status=active&q=담당", headers=h)).json()["items"]
    assert {i["display_name"] for i in found} == {"회의 담당", "모집 담당"}
    assert (await client.get("/api/admin/members?status=active&q=%25", headers=h)).json()["items"] == []  # LIKE 기호는 글자로


async def test_detail_and_admin_only(committed_db, client) -> None:
    _, h = await admin_headers(committed_db, client)
    m = await active(committed_db)
    detail = (await client.get(f"/api/admin/members/{m.id}", headers=h)).json()
    assert detail["email"] == m.email and detail["groups"] == [] and detail["active_sessions"] == 0
    assert (await client.get("/api/admin/members/999999", headers=h)).status_code == 404
    mh = await session_of(client, m, ip="203.0.113.41")
    assert (await client.get("/api/admin/members?status=active", headers=mh)).status_code == 403
    assert (await client.patch(f"/api/admin/members/{m.id}", json={"level": 5}, headers=mh)).status_code == 403


# ── 고치기 ──────────────────────────────────────────────────


async def test_level_change_closes_pending_request(committed_db, client) -> None:
    _, h = await admin_headers(committed_db, client)
    m = await active(committed_db, level=2)
    committed_db.add(LevelRequest(member_id=m.id, from_level=2, to_level=5, reason="활동"))
    await committed_db.commit()
    r = await client.patch(f"/api/admin/members/{m.id}", json={"level": 4, "reason": "활동 많음"}, headers=h)
    assert r.json()["level"] == 4
    req = (await committed_db.execute(select(LevelRequest))).scalar_one()
    assert req.status == "cancelled"
    event = (await committed_db.execute(select(OutboxEvent).where(OutboxEvent.type == "level.decided"))).scalar_one()
    assert event.payload == {"request_id": req.id}  # 신청자에게 알린다(검토 v5 U-2)
    log = (await committed_db.execute(select(ModerationLog).where(ModerationLog.action == "member.update"))).scalar_one()
    assert (log.before, log.after, log.reason) == ({"level": 2}, {"level": 4}, "활동 많음")


async def test_display_name_rules(committed_db, client) -> None:
    _, h = await admin_headers(committed_db, client)
    a = await active(committed_db, display_name="겹치는 이름")
    b = await active(committed_db)
    assert (await client.patch(f"/api/admin/members/{b.id}", json={"display_name": "겹치는이름"}, headers=h)).status_code == 409
    assert (await client.patch(f"/api/admin/members/{b.id}", json={"display_name": "​"}, headers=h)).status_code == 422
    assert (await client.patch(f"/api/admin/members/{b.id}", json={"display_name": "새 이름"}, headers=h)).json()["display_name"] == "새 이름"
    assert a.id


async def test_email_change_needs_reauth_and_protects_admins(committed_db, client, monkeypatch) -> None:
    from app.core import rate_limit
    from app.core.rate_limit import Limit

    monkeypatch.setitem(rate_limit.LIMITS, "auth.reauth", Limit(20, 900))  # 한 시험에서 재확인을 여러 번 한다
    _, h = await admin_headers(committed_db, client)
    m = await active(committed_db)
    other_admin = await active(committed_db, is_admin=True)
    taken = await active(committed_db, email="taken@example.com")
    url = f"/api/admin/members/{m.id}"
    r = await client.patch(url, json={"email": "new@example.com"}, headers=h)  # 비밀번호 없음 — 재확인 시도로 세지 않는다
    assert (r.status_code, r.json()["errors"][0]["field"]) == (422, "password")
    assert (await client.patch(url, json={"email": "new@example.com", "password": "wrong password here"}, headers=h)).status_code == 403
    assert (await client.patch(url, json={"email": "bad", "password": TEST_PASSWORD}, headers=h)).status_code == 422
    assert (await client.patch(url, json={"email": taken.email, "password": TEST_PASSWORD}, headers=h)).status_code == 409
    r = await client.patch(f"/api/admin/members/{other_admin.id}", json={"email": "x@example.com", "password": TEST_PASSWORD}, headers=h)
    assert (r.status_code, r.json()["code"]) == (403, "target_is_admin")
    assert (await client.patch(url, json={"email": " New@Example.com ", "password": TEST_PASSWORD}, headers=h)).json()["email"] == "new@example.com"
    log = (await committed_db.execute(select(ModerationLog).where(ModerationLog.action == "member.update"))).scalar_one()
    assert log.after == {"email": "n***@e***.com"} and "@example.test" not in str(log.before)


# ── 운영자 지정·해제(§4.11) ─────────────────────────────────


async def test_promote_shrinks_persistent_sessions(committed_db, client) -> None:
    _, h = await admin_headers(committed_db, client)
    m = await active(committed_db)
    await session_of(client, m, ip="203.0.113.42", persistent=True)  # 회원 기준 30일
    r = await client.patch(f"/api/admin/members/{m.id}", json={"is_admin": True, "password": TEST_PASSWORD}, headers=h)
    assert r.json()["is_admin"] is True
    s = (await committed_db.execute(select(LoginSession).where(LoginSession.member_id == m.id))).scalar_one()
    assert s.expires_at - s.created_at <= timedelta(days=7)  # 운영자 기준으로 줄었다
    # 해제해도 늘리지 않는다
    member_id = m.id
    await client.patch(f"/api/admin/members/{member_id}", json={"is_admin": False, "password": TEST_PASSWORD}, headers=h)
    committed_db.expire_all()
    s = (await committed_db.execute(select(LoginSession).where(LoginSession.member_id == member_id))).scalar_one()
    assert s.expires_at - s.created_at <= timedelta(days=7)


async def test_last_admin_cannot_be_unset(committed_db, client) -> None:
    admin, h = await admin_headers(committed_db, client)
    r = await client.patch(f"/api/admin/members/{admin.id}", json={"is_admin": False, "password": TEST_PASSWORD}, headers=h)
    assert (r.status_code, r.json()["code"]) == (409, "last_admin")


async def test_two_admins_unsetting_each_other_one_wins(committed_db, client) -> None:
    a, ha = await admin_headers(committed_db, client)
    b = await active(committed_db, is_admin=True)
    hb = await session_of(client, b, ip="203.0.113.43")
    results = await asyncio.gather(
        client.patch(f"/api/admin/members/{b.id}", json={"is_admin": False, "password": TEST_PASSWORD}, headers=ha),
        client.patch(f"/api/admin/members/{a.id}", json={"is_admin": False, "password": TEST_PASSWORD}, headers=hb),
    )
    codes = sorted(r.status_code for r in results)
    # 하나만 성공 — 다른 하나는 마지막 운영자 보호(409) 또는 이미 운영자가 아니게 된 쪽의 권한 거부(403). 교착 없음
    assert codes[0] == 200 and codes[1] in (403, 409)
    admins = (await committed_db.execute(select(Member.id).where(Member.is_admin))).scalars().all()
    assert len(admins) == 1


# ── 강제 로그아웃 ───────────────────────────────────────────


async def test_revoke_sessions(committed_db, client) -> None:
    _, h = await admin_headers(committed_db, client)
    m = await active(committed_db)
    mh = await session_of(client, m, ip="203.0.113.44")
    url = f"/api/admin/members/{m.id}/revoke-sessions"
    assert (await client.post(url, json={"password": "wrong password here"}, headers=h)).status_code == 403
    assert (await client.post(url, json={"password": TEST_PASSWORD, "reason": "기기 분실"}, headers=h)).json() == {"revoked": 1}
    assert await whoami(client, mh["X-Session"]) is None


# ── 그룹 ────────────────────────────────────────────────────


async def test_groups_crud_and_members(committed_db, client) -> None:
    _, h = await admin_headers(committed_db, client)
    m1 = await active(committed_db)
    m2 = await active(committed_db)
    gone = await active(committed_db, status="withdrawn", withdrawn_at=datetime.now(UTC))
    g = (await client.post("/api/admin/member-groups", json={"name": "운영진"}, headers=h)).json()
    assert (await client.post("/api/admin/member-groups", json={"name": "운영진"}, headers=h)).status_code == 409
    r = await client.put(f"/api/admin/member-groups/{g['id']}/members", json={"member_ids": [m1.id, gone.id]}, headers=h)
    assert r.status_code == 422  # 탈퇴 회원은 넣을 수 없다
    r = await client.put(f"/api/admin/member-groups/{g['id']}/members", json={"member_ids": [m1.id, m2.id]}, headers=h)
    assert {x["id"] for x in r.json()["members"]} == {m1.id, m2.id}
    r = await client.put(f"/api/admin/member-groups/{g['id']}/members", json={"member_ids": [m2.id]}, headers=h)
    assert [x["id"] for x in r.json()["members"]] == [m2.id]
    assert (await client.patch(f"/api/admin/member-groups/{g['id']}", json={"name": "모임 담당"}, headers=h)).json()["name"] == "모임 담당"
    listed = (await client.get("/api/admin/member-groups", headers=h)).json()["items"]
    assert listed == [{"id": g["id"], "name": "모임 담당", "description": None, "members": 1}]
    assert (await client.get(f"/api/admin/members/{m2.id}", headers=h)).json()["groups"] == [{"id": g["id"], "name": "모임 담당"}]
    logs = (await committed_db.execute(select(ModerationLog.target_type).where(ModerationLog.action.like("group.%")))).scalars().all()
    assert set(logs) == {"group"}


async def test_delete_group_removes_board_access(committed_db, client) -> None:
    _, h = await admin_headers(committed_db, client)
    g = (await client.post("/api/admin/member-groups", json={"name": "명부 그룹"}, headers=h)).json()
    board = await make_board(committed_db)
    committed_db.add(BoardAccess(board_id=board.id, subject_type="group", subject_id=g["id"], can_read=True))
    await committed_db.commit()
    assert (await client.delete(f"/api/admin/member-groups/{g['id']}", headers=h)).status_code == 204
    assert (await committed_db.execute(select(BoardAccess))).first() is None
    assert (await client.get(f"/api/admin/member-groups/{g['id']}", headers=h)).status_code == 404
