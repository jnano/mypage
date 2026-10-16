"""로그인·세션·재동의·로그아웃 — 인증 설계도 §4.3~§4.5·§3.6·§9"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import keys, login as login_service
from app.auth.sessions import hash_token
from app.core import rate_limit
from app.core.rate_limit import Limit
from app.models import LoginSession, Member, PrivacyNotice
from tests.factories import TEST_PASSWORD, ensure_test_notice, make_member

pytestmark = pytest.mark.anyio

IP = "198.51.100.1"


async def login(
    client: AsyncClient,
    email: str,
    password: str = TEST_PASSWORD,
    *,
    persistent: bool = False,
    ip: str = IP,
    device: str | None = None,
    session: str | None = None,
):
    headers = {"X-Client-IP": ip}
    if device:
        headers["X-Device"] = device
    if session:
        headers["X-Session"] = session
    return await client.post(
        "/api/auth/login",
        json={"email": email, "password": password, "persistent": persistent, "user_agent": "시험 브라우저"},
        headers=headers,
    )


async def whoami(client: AsyncClient, token: str) -> int | None:
    """그 토큰으로 본 보는 사람(page-state 의 viewer)"""
    r = await client.get("/api/me/notifications", headers={"X-Session": token})
    return None if r.status_code == 401 else r.status_code


async def member(db: AsyncSession, **kw) -> Member:
    m = await make_member(db, **kw)
    await db.commit()
    return m


# ── 성공·만료(§3.2.1) ───────────────────────────────────────


async def test_login_issues_session_cookie_values(committed_db, client) -> None:
    m = await member(committed_db)
    r = await login(client, (m.email or "").upper() + "  ")  # 정규화: 공백 제거 + 소문자
    assert r.status_code == 200 and r.headers["cache-control"] == "private, no-store"
    body = r.json()
    assert body["session_expires_at"] is None and body["device_token"] is None  # 유지 안 함
    row = (await committed_db.execute(select(LoginSession).where(LoginSession.member_id == m.id))).scalar_one()
    assert row.token_hash == hash_token(body["session_token"]) and row.user_agent == "시험 브라우저"
    assert timedelta(hours=11, minutes=59) < row.expires_at - row.created_at <= timedelta(hours=12)
    assert await whoami(client, body["session_token"]) == 200


@pytest.mark.parametrize(("is_admin", "days"), [(False, 30), (True, 7)])
async def test_persistent_lifetime(committed_db, client, is_admin: bool, days: int) -> None:
    m = await member(committed_db, is_admin=is_admin)
    body = (await login(client, m.email or "", persistent=True)).json()
    expires = datetime.fromisoformat(body["session_expires_at"])
    assert timedelta(days=days) - timedelta(minutes=1) < expires - datetime.now(UTC) <= timedelta(days=days)
    assert keys.device_matches(body["device_token"], m.email or "")


async def test_expired_or_revoked_session_is_guest(committed_db, client) -> None:
    m = await member(committed_db)
    token = (await login(client, m.email or "")).json()["session_token"]
    await committed_db.execute(
        update(LoginSession).where(LoginSession.member_id == m.id).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    await committed_db.commit()
    assert await whoami(client, token) is None


# ── 계정 열거(§7.1) ─────────────────────────────────────────


async def test_failures_look_the_same(committed_db, client) -> None:
    m = await member(committed_db)
    gone = await member(committed_db, status="withdrawn", withdrawn_at=datetime.now(UTC))
    responses = [
        await login(client, "nobody@example.test"),
        await login(client, m.email or "", "wrong password here"),
        await login(client, "not an email at all"),
        await login(client, f"gone{gone.id}@example.test"),
    ]
    assert {(r.status_code, r.text) for r in responses} == {(responses[0].status_code, responses[0].text)}
    assert responses[0].status_code == 401 and responses[0].json()["code"] == "login_failed"


async def test_pending_told_only_with_right_password(committed_db, client) -> None:
    m = await member(committed_db, status="pending")
    assert (await login(client, m.email or "")).json()["code"] == "signup_pending"
    assert (await login(client, m.email or "", "wrong password here")).json()["code"] == "login_failed"


# ── 잠금 공격·기기 쿠키(§4.3.1) ─────────────────────────────


@pytest.fixture
def small_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    """한도를 줄여 같은 성질을 빠르게 본다 — 이메일 단독 3회, 쿠키 단위 2회"""
    monkeypatch.setitem(rate_limit.LIMITS, "auth.login_account", Limit(3, 900))
    monkeypatch.setitem(rate_limit.LIMITS, "auth.login_device", Limit(2, 900))


async def test_victim_with_device_cookie_survives_lockout(committed_db, client, small_limits) -> None:
    m = await member(committed_db)
    device = (await login(client, m.email or "", persistent=True, ip="203.0.113.1")).json()["device_token"]
    for i in range(3):  # 공격자가 여러 IP 로 틀린다 → 이메일 단독 한도 소진
        await login(client, m.email or "", "wrong password here", ip=f"192.0.2.{i + 10}")
    assert (await login(client, m.email or "", ip="203.0.113.1")).status_code == 429
    assert (await login(client, m.email or "", ip="203.0.113.1", device=device)).status_code == 200


async def test_other_ip_failures_do_not_lock_victim_ip(committed_db, client, monkeypatch) -> None:
    monkeypatch.setitem(rate_limit.LIMITS, "auth.login", Limit(2, 900))
    m = await member(committed_db)
    for _ in range(3):
        await login(client, m.email or "", "wrong password here", ip="192.0.2.50")
    assert (await login(client, m.email or "", ip="192.0.2.50")).status_code == 429
    assert (await login(client, m.email or "", ip="203.0.113.7")).status_code == 200


async def test_device_cookie_exemption_has_its_own_cap(committed_db, client, small_limits) -> None:
    m = await member(committed_db)
    device = (await login(client, m.email or "", persistent=True)).json()["device_token"]
    codes = [(await login(client, m.email or "", "wrong password here", ip=f"192.0.2.{i}", device=device)).status_code for i in range(3)]
    assert codes == [401, 401, 429]  # 훔친 쿠키로 IP 를 바꿔 가며 추측해도 쿠키 단위 상한


async def test_device_cookie_must_match_email_signature_and_age(committed_db, client, monkeypatch) -> None:
    m = await member(committed_db)
    other = await member(committed_db)
    good = keys.device_token(m.email or "")
    assert keys.device_matches(good, m.email or "")
    assert not keys.device_matches(keys.device_token(other.email or ""), m.email or "")  # 다른 이메일의 것
    assert not keys.device_matches(good[:-2] + "AA", m.email or "")  # 서명 틀림
    old = keys.sign("device", good.split(".")[0], str(int((datetime.now(UTC) - timedelta(days=366)).timestamp())))
    assert not keys.device_matches(old, m.email or "")  # 1년 지남
    # 유지 안 함 로그인은 기기 쿠키를 받지 않는다
    assert (await login(client, m.email or "")).json()["device_token"] is None


def test_subkeys_do_not_cross_purposes() -> None:
    device = keys.device_token("a@example.test")
    body, mac = device.rsplit(".", 1)
    forged = f"1.1.{body.split('.')[1]}.{mac}"  # 기기 쿠키의 서명으로 재동의 토큰을 만들 수 없다
    assert keys.read_consent_token(forged) is None
    assert keys.read_consent_token(keys.consent_token(7, True)) == (7, True)
    assert keys.subkey("device") != keys.subkey("consent") != keys.subkey("form")


# ── 제한 순서·한도 대기(§7.5·§7.7) ──────────────────────────


async def test_limited_login_does_not_hash(committed_db, client, monkeypatch) -> None:
    monkeypatch.setitem(rate_limit.LIMITS, "auth.login_ip", Limit(1, 900))
    m = await member(committed_db)
    calls = []
    real = login_service.verify_password
    monkeypatch.setattr(login_service, "verify_password", lambda h, p: calls.append(1) or real(h, p))
    await login(client, m.email or "", ip="192.0.2.99")
    assert (await login(client, m.email or "", ip="192.0.2.99")).status_code == 429
    assert len(calls) == 1


async def test_slot_wait_then_full_computation(monkeypatch) -> None:
    import anyio

    from app.core import threads

    monkeypatch.setitem(threads.LIMITS, "argon2", 1)
    monkeypatch.setattr(threads, "_limiters", {})
    monkeypatch.setattr(threads, "_workers", {})
    results: list[str] = []

    async def job(name: str, seconds: float) -> None:
        def work() -> str:
            import time

            time.sleep(seconds)
            return name

        try:
            results.append(await threads.run_in_thread_within("argon2", 0.5, work))
        except threads.SlotTimeout:
            results.append(f"{name}:timeout")

    async with anyio.create_task_group() as tg:
        tg.start_soon(job, "first", 0.2)  # 자리를 얻으면 끝까지
        await anyio.sleep(0.05)
        tg.start_soon(job, "second", 0.0)  # 0.5초 안에 자리가 난다
    assert results == ["first", "second"]
    async with anyio.create_task_group() as tg:
        tg.start_soon(job, "long", 1.0)
        await anyio.sleep(0.05)
        tg.start_soon(job, "late", 0.0)  # 기한 안에 자리가 안 난다
    assert results[2:] == ["late:timeout", "long"]


# ── 세션 경계(§4.4) ─────────────────────────────────────────


async def test_session_header_needs_internal_secret(committed_db, client, browser) -> None:
    m = await member(committed_db)
    token = (await login(client, m.email or "")).json()["session_token"]
    r = await browser.get("/api/me/notifications", headers={"X-Session": token})  # rewrites 로 온 브라우저 요청
    assert r.status_code == 401


async def test_reads_do_not_write_sessions_but_writes_touch(committed_db, client) -> None:
    m = await member(committed_db)
    token = (await login(client, m.email or "")).json()["session_token"]
    old = datetime.now(UTC) - timedelta(minutes=30)
    await committed_db.execute(update(LoginSession).where(LoginSession.member_id == m.id).values(last_write_at=old))
    await committed_db.commit()
    await client.get("/api/me/notifications", headers={"X-Session": token})
    member_id = m.id

    async def stamp():
        committed_db.expire_all()
        return await committed_db.execute(select(LoginSession.last_write_at).where(LoginSession.member_id == member_id))

    assert (await stamp()).scalar_one() == old
    r = await client.post("/api/me/notifications/read", json={"all": True}, headers={"X-Session": token})
    assert r.status_code < 300
    assert (await stamp()).scalar_one() > old


# ── 폐기(§4.5) ──────────────────────────────────────────────


async def test_logout_this_device_and_relogin_revokes_previous(committed_db, client) -> None:
    m = await member(committed_db)
    first = (await login(client, m.email or "")).json()["session_token"]
    second = (await login(client, m.email or "", session=first)).json()["session_token"]  # 같은 브라우저 재로그인
    assert await whoami(client, first) is None and await whoami(client, second) == 200
    assert (await client.post("/api/auth/logout", headers={"X-Session": second})).status_code == 204
    assert await whoami(client, second) is None
    assert (await client.post("/api/auth/logout")).status_code == 204  # 세션 없이도 성공


async def test_logout_all_devices(committed_db, client) -> None:
    m = await member(committed_db)
    a = (await login(client, m.email or "")).json()["session_token"]
    b = (await login(client, m.email or "", ip="203.0.113.9")).json()["session_token"]
    assert (await client.post("/api/auth/logout-all", headers={"X-Session": a})).status_code == 204
    assert await whoami(client, a) is None and await whoami(client, b) is None
    assert (await client.post("/api/auth/logout-all")).status_code == 401


# ── 재동의(§3.6, 검토 v2 C-2) ───────────────────────────────


async def test_reconsent_withholds_session_until_agreed(committed_db, client) -> None:
    m = await member(committed_db)
    await ensure_test_notice(committed_db)
    committed_db.add(
        PrivacyNotice(version="v-next", body="수집 항목이 바뀐 고지", requires_reconsent=True, published_at=datetime.now(UTC))
    )
    await committed_db.commit()
    r = (await login(client, m.email or "", persistent=True)).json()
    assert set(r) == {"consent_token"}  # 세션 없음
    assert (await committed_db.execute(select(LoginSession.id).where(LoginSession.member_id == m.id))).first() is None
    current = (await client.get("/api/privacy-notices/current")).json()
    assert current["version"] == "v-next" and current["requires_reconsent"] is True
    agreed = (await client.post("/api/auth/privacy-consent", json={"consent_token": r["consent_token"]})).json()
    assert await whoami(client, agreed["session_token"]) == 200
    # 같은 토큰은 한 번만 — 두 번째는 401 이고 세션은 하나(검토 v3 R-1)
    again = await client.post("/api/auth/privacy-consent", json={"consent_token": r["consent_token"]})
    assert again.status_code == 401 and again.json()["code"] == "consent_expired"
    sessions_made = await committed_db.execute(select(LoginSession.id).where(LoginSession.member_id == m.id))
    assert len(sessions_made.all()) == 1
    assert agreed["device_token"] is not None  # 로그인 때 고른 '유지'를 이어받는다
    member_id, email = m.id, m.email or ""
    committed_db.expire_all()
    assert (await committed_db.get(Member, member_id)).privacy_version == "v-next"
    # 동의한 뒤에는 바로 세션
    assert "session_token" in (await login(client, email)).json()


async def test_consent_token_rejects_bad_or_old(committed_db, client) -> None:
    m = await member(committed_db)
    stale = keys.sign("consent", str(m.id), "0", str(int((datetime.now(UTC) - timedelta(minutes=6)).timestamp())))
    for token in (stale, "1.0.123.bad", keys.consent_token(m.id, False)[:-3] + "xyz"):
        r = await client.post("/api/auth/privacy-consent", json={"consent_token": token})
        assert r.status_code == 401 and r.json()["code"] == "consent_expired"


# ── 토큰이 새지 않는다(§9 '토큰 로그') ──────────────────────


async def test_tokens_absent_from_error_responses(committed_db, client) -> None:
    m = await member(committed_db)
    token = (await login(client, m.email or "")).json()["session_token"]
    r = await login(client, m.email or "", "wrong password here", session=token)
    assert token not in r.text and "session_token" not in r.text


async def test_every_failure_response_counts_for_alert(committed_db) -> None:
    """실패 응답을 만드는 한 곳에서 센다 — 어느 실패 경로도 경보 집계에서 빠지지 않는다(검토 v5 U-3)"""
    from app.models import RateLimitCounter

    for _ in range(3):
        problem = await login_service.login_failed()
        assert (problem.status, problem.code) == (401, "login_failed")
    counted = (await committed_db.execute(select(RateLimitCounter.count).where(RateLimitCounter.key == "auth.login_failed_site:site"))).scalar_one()
    assert counted == 3
