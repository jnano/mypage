"""가입 신청·승인·거부·고지 판 관리 — 인증 설계도 §4.1·§4.2·§3.6·§9(검토 v3 R-2·R-4 포함)"""

import asyncio
from datetime import UTC, datetime, timedelta

import argon2
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import keys
from app.auth import login as login_service
from app.core import form_guard, rate_limit
from app.core.rate_limit import Limit
from app.models import Member, ModerationLog, Notification, OutboxEvent, SiteSetting, WithdrawnEmailMark
from app.worker import handlers
from tests.factories import TEST_NOTICE, TEST_PASSWORD, ensure_test_notice, make_member
from tests.test_auth_login import login

pytestmark = pytest.mark.anyio

GOOD = "a sentence long enough to pass"


@pytest.fixture(autouse=True)
def no_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(form_guard, "MIN_ELAPSED", 0)


async def open_signup(db: AsyncSession, **overrides) -> None:
    await ensure_test_notice(db)
    db.add(SiteSetting(key="signup", value={"open": True} | overrides))
    await db.commit()


async def form(client: AsyncClient) -> dict:
    return (await client.get("/api/auth/signup-form")).json()


async def apply(client: AsyncClient, **kw):
    f = await form(client)
    body = {
        "email": "new@example.com",
        "password": GOOD,
        "display_name": "새 회원",
        "signup_note": "회의 안내를 보려고 가입합니다",
        "age14": True,
        "privacy_version": TEST_NOTICE,
        "privacy_agreed": True,
        "form_token": f["form_token"],
    } | kw
    return await client.post("/api/auth/signup", json=body, headers={"X-Client-IP": kw.pop("ip", "198.51.100.20")})


# ── 가입 화면·열림(§4.1-1, §3.6 '게시된 판이 없으면 닫힘') ───


async def test_closed_by_default_and_without_notice(committed_db, client) -> None:
    assert (await form(client)) == {"open": False, "contact_text": "", "password_min_length": 15, "notice": None, "form_token": None}
    committed_db.add(SiteSetting(key="signup", value={"open": True, "contact_text": "문의: 사무실"}))
    await committed_db.commit()
    assert (await form(client))["open"] is False  # 열었어도 게시된 고지 판이 없으면 닫힘
    r = await client.post("/api/auth/signup", json={"email": "a@example.com", "password": GOOD, "display_name": "가", "privacy_version": "x", "form_token": "x"})
    assert r.status_code == 403 and r.json()["code"] == "signup_closed"


async def test_open_form_bundles_token_and_notice(committed_db, client) -> None:
    await open_signup(committed_db, contact_text="문의: 사무실")
    f = await form(client)
    assert f["open"] is True and f["notice"]["version"] == TEST_NOTICE and f["contact_text"] == "문의: 사무실"
    assert keys.verify("form", f["form_token"], 2, form_guard.MAX_AGE)[0] == "signup"
    assert (await client.get("/api/auth/signup-form")).headers["cache-control"] == "private, no-store"


# ── 폼 토큰·honeypot(§9 '폼 토큰') ─────────────────────────


async def test_form_guard_rejects(committed_db, client, monkeypatch) -> None:
    await open_signup(committed_db)
    old = keys.sign("form", "signup", str(int((datetime.now(UTC) - timedelta(hours=3)).timestamp())))
    for kw in (
        {"form_token": "signup.1.bad"},  # 서명 틀림
        {"form_token": keys.sign("form", "comment", str(int(datetime.now(UTC).timestamp())))},  # 다른 폼
        {"form_token": old},  # 수명 지남
        {"website": "http://spam.example"},  # honeypot
        {"form_token": keys.device_token("a@example.com")},  # 다른 용도의 서명
    ):
        r = await apply(client, **kw)
        assert (r.status_code, r.json()["code"]) == (422, "form_rejected"), kw
    monkeypatch.setattr(form_guard, "MIN_ELAPSED", 60)
    assert (await apply(client)).json()["code"] == "form_rejected"  # 너무 빨리 냄


# ── 신청(§4.1) ──────────────────────────────────────────────


async def test_signup_creates_pending_and_notifies_admins(committed_db, client) -> None:
    await open_signup(committed_db, contact_text="문의: 사무실")
    admin = await make_member(committed_db, is_admin=True)
    await committed_db.commit()
    r = await apply(client, email="  New@Example.COM ")
    assert r.status_code == 202 and r.json()["contact_text"] == "문의: 사무실"
    m = (await committed_db.execute(select(Member).where(Member.email == "new@example.com"))).scalar_one()
    assert (m.status, m.display_name_key, m.privacy_version, m.signup_note) == ("pending", "새회원", TEST_NOTICE, "회의 안내를 보려고 가입합니다")
    assert m.age14_confirmed_at and m.password_hash and m.password_hash.startswith("$argon2id$")
    event = (await committed_db.execute(select(OutboxEvent).where(OutboxEvent.type == "member.signup_pending"))).scalar_one()
    await handlers.signup_pending(committed_db, event)
    await committed_db.commit()
    n = (await committed_db.execute(select(Notification).where(Notification.recipient_id == admin.id))).scalar_one()
    assert (n.type, n.actor_id) == ("member.signup_pending", m.id)
    inbox = (await client.get("/api/me/notifications", headers=_session(await _login_token(client, admin)))).json()
    assert inbox["items"][0]["path"] == "/admin/members/pending" and inbox["items"][0]["masked"] is None


async def _login_token(client: AsyncClient, member: Member) -> str:
    return (await login(client, member.email or "", ip="203.0.113.200")).json()["session_token"]


def _session(token: str) -> dict[str, str]:
    return {"X-Session": token}


async def test_duplicate_email_same_response_no_second_row(committed_db, client) -> None:
    await open_signup(committed_db)
    first = await apply(client)
    second = await apply(client, display_name="다른 이름")
    assert (first.status_code, first.json()) == (second.status_code, second.json())
    assert len((await committed_db.execute(select(Member.id).where(Member.email == "new@example.com"))).all()) == 1


async def test_name_rules(committed_db, client) -> None:
    await open_signup(committed_db)
    await make_member(committed_db, display_name="회원하나")
    await committed_db.commit()
    r = await apply(client, display_name="회원 하나")  # 활동 회원과 정규화 키가 같다
    assert (r.status_code, r.json()["code"]) == (409, "display_name_taken")
    r = await apply(client, display_name="ADMIN")  # 예약어(정규화 키로 비교)
    assert r.json()["errors"][0] == {"field": "display_name", "message": "쓸 수 없는 표시 이름입니다"}
    # 대기 신청은 이름을 선점하지 못한다 — 같은 이름의 두 번째 신청도 접수
    assert (await apply(client, email="p1@example.com", display_name="대기 이름")).status_code == 202
    assert (await apply(client, email="p2@example.com", display_name="대기이름")).status_code == 202


async def test_validation_errors_listed_by_field(committed_db, client) -> None:
    await open_signup(committed_db, password_min_length=20)
    r = await apply(client, email="bad", password="short pass", age14=False, privacy_agreed=False)
    assert r.status_code == 422
    assert {e["field"] for e in r.json()["errors"]} == {"email", "password", "age14", "privacy_agreed"}
    r = await apply(client, privacy_version="older")
    assert r.json()["code"] == "privacy_notice_changed"


async def test_site_wide_hourly_cap(committed_db, client) -> None:
    await open_signup(committed_db, hourly_limit=1)
    assert (await apply(client, email="a1@example.com", ip="198.51.100.1")).status_code == 202
    assert (await apply(client, email="a2@example.com", ip="198.51.100.2")).status_code == 429


async def test_pending_member_cannot_get_session(committed_db, client) -> None:
    await open_signup(committed_db)
    await apply(client)
    assert (await login(client, "new@example.com", GOOD)).json()["code"] == "signup_pending"


# ── 승인·거부(§4.2) ─────────────────────────────────────────


async def _admin_client(committed_db, client) -> dict[str, str]:
    admin = await make_member(committed_db, is_admin=True, display_name="운영자")
    await committed_db.commit()
    return _session(await _login_token(client, admin))


async def test_approve_sets_level_clears_note_and_logs_masked(committed_db, client) -> None:
    await open_signup(committed_db, default_level=2)
    await apply(client)
    h = await _admin_client(committed_db, client)
    pending = (await client.get("/api/admin/members?status=pending", headers=h)).json()["items"]
    assert [p["email"] for p in pending] == ["new@example.com"]
    r = await client.post(f"/api/admin/members/{pending[0]['id']}/approve", json={}, headers=h)
    assert r.json() == {"id": pending[0]["id"], "status": "active", "level": 2}
    committed_db.expire_all()
    m = await committed_db.get(Member, pending[0]["id"])
    assert m.signup_note is None and m.approved_by is not None
    log = (await committed_db.execute(select(ModerationLog).where(ModerationLog.action == "member.approve"))).scalar_one()
    assert log.after["email"] == "n***@e***.com" and "signup_note" not in log.after
    assert "session_token" in (await login(client, "new@example.com", GOOD)).json()


async def test_approve_name_conflict_then_fix(committed_db, client) -> None:
    await open_signup(committed_db)
    await apply(client, display_name="겹칠 이름")
    h = await _admin_client(committed_db, client)
    await make_member(committed_db, display_name="겹칠이름")
    await committed_db.commit()
    pid = (await client.get("/api/admin/members", headers=h)).json()["items"][0]["id"]
    r = await client.post(f"/api/admin/members/{pid}/approve", json={}, headers=h)
    assert (r.status_code, r.json()["code"]) == (409, "display_name_taken")
    assert (await client.post(f"/api/admin/members/{pid}/approve", json={"display_name": "고친 이름"}, headers=h)).status_code == 200


async def test_concurrent_approvals_of_same_key_one_wins(committed_db, client) -> None:
    await open_signup(committed_db)
    await apply(client, email="c1@example.com", display_name="같은 이름")
    await apply(client, email="c2@example.com", display_name="같은이름")
    h = await _admin_client(committed_db, client)
    ids = [p["id"] for p in (await client.get("/api/admin/members", headers=h)).json()["items"]]
    results = await asyncio.gather(*(client.post(f"/api/admin/members/{i}/approve", json={}, headers=h) for i in ids))
    assert sorted(r.status_code for r in results) == [200, 409]  # 500 이 아니다(부분 UNIQUE 위반 → 409)


async def test_reject_many_deletes_and_flags_withdrawn_mark(committed_db, client) -> None:
    await open_signup(committed_db)
    await apply(client, email="r1@example.com", display_name="거부 하나")
    await apply(client, email="r2@example.com", display_name="거부 둘")
    committed_db.add(WithdrawnEmailMark(email_hmac=keys.email_hmac("r2@example.com"), expires_at=datetime.now(UTC) + timedelta(days=1)))
    await committed_db.commit()
    h = await _admin_client(committed_db, client)
    items = (await client.get("/api/admin/members", headers=h)).json()["items"]
    assert [i["recently_withdrawn_under_sanction"] for i in items] == [False, True]
    r = await client.post("/api/admin/members/reject", json={"ids": [i["id"] for i in items], "reason": "확인 안 됨"}, headers=h)
    assert r.json() == {"rejected": 2}
    assert (await committed_db.execute(select(Member.id).where(Member.status == "pending"))).first() is None


async def test_member_admin_is_admin_only(committed_db, client) -> None:
    m = await make_member(committed_db)
    await committed_db.commit()
    h = _session(await _login_token(client, m))
    assert (await client.get("/api/admin/members", headers=h)).status_code == 403
    assert (await client.get("/api/admin/privacy-notices", headers=h)).status_code == 403


# ── 고지 판(§3.6) ───────────────────────────────────────────


async def test_published_notice_is_immutable(committed_db, client) -> None:
    h = await _admin_client(committed_db, client)
    assert (await client.post("/api/admin/privacy-notices", json={"version": "2026-11-01", "body": "초안"}, headers=h)).status_code == 201
    assert (await client.patch("/api/admin/privacy-notices/2026-11-01", json={"body": "고친 초안"}, headers=h)).json()["body"] == "고친 초안"
    assert (await client.post("/api/admin/privacy-notices/2026-11-01/publish", headers=h)).status_code == 200
    r = await client.patch("/api/admin/privacy-notices/2026-11-01", json={"body": "게시 뒤"}, headers=h)
    assert (r.status_code, r.json()["code"]) == (409, "notice_published")
    assert (await client.post("/api/admin/privacy-notices", json={"version": "bad version!", "body": "x"}, headers=h)).status_code == 422


async def test_reconsent_publish_revokes_older_agreements(committed_db, client) -> None:
    h = await _admin_client(committed_db, client)
    m = await make_member(committed_db)
    await committed_db.commit()
    token = await _login_token(client, m)
    await client.post("/api/admin/privacy-notices", json={"version": "v-re", "body": "항목이 바뀜", "requires_reconsent": True}, headers=h)
    r = (await client.post("/api/admin/privacy-notices/v-re/publish", headers=h)).json()
    assert r["sessions_revoked"] >= 2  # 회원과 운영자 자신(둘 다 옛 판 동의)
    assert (await client.get("/api/me/notifications", headers=_session(token))).status_code == 401
    assert set((await login(client, m.email or "", ip="203.0.113.201")).json()) == {"consent_token"}


async def test_non_reconsent_notice_announced_once(committed_db, client) -> None:
    h = await _admin_client(committed_db, client)
    m = await make_member(committed_db)
    await committed_db.commit()
    await _login_token(client, m)  # 지난 로그인
    await client.post("/api/admin/privacy-notices", json={"version": "v-text", "body": "문구 정리"}, headers=h)
    r = (await client.post("/api/admin/privacy-notices/v-text/publish", headers=h)).json()
    assert r["sessions_revoked"] == 0
    first = (await login(client, m.email or "", ip="203.0.113.202")).json()
    assert first["notices"] == ["privacy_updated"]
    assert (await login(client, m.email or "", ip="203.0.113.203")).json()["notices"] == []


# ── 검토 v3 R-2·R-4 ─────────────────────────────────────────


def test_dummy_hash_uses_current_parameters() -> None:
    hasher = argon2.PasswordHasher()
    params = argon2.extract_parameters(login_service.dummy_hash())
    assert (params.type, params.time_cost, params.memory_cost, params.parallelism, params.hash_len, params.salt_len) == (
        hasher.type, hasher.time_cost, hasher.memory_cost, hasher.parallelism, hasher.hash_len, hasher.salt_len,
    )  # fmt: skip


async def test_ip_counted_first(committed_db, client, monkeypatch) -> None:
    """IP 단독이 먼저 — 한 IP 의 폭주가 막힌 뒤에는 이메일 키를 더 소진하지 않는다(검토 v3 R-4)"""
    monkeypatch.setitem(rate_limit.LIMITS, "auth.login_ip", Limit(2, 900))
    monkeypatch.setitem(rate_limit.LIMITS, "auth.login_account", Limit(4, 900))
    m = await make_member(committed_db)
    await committed_db.commit()
    for _ in range(5):
        await login(client, m.email or "", "wrong password here", ip="192.0.2.77")
    # 이메일 단독 키는 IP 한도까지만(2번) 셌다 — 다른 IP 의 피해자는 들어온다
    assert (await login(client, m.email or "", TEST_PASSWORD, ip="203.0.113.77")).status_code == 200
