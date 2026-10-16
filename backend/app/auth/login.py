"""로그인·재동의·로그아웃 — 인증 설계도 §4.3·§3.6·§4.5.

순서(본 설계서 §3.1-4): ① 입력 검증 → ② 요청 수 제한(해시 전에, 별도 autocommit) → ③ argon2(한도 자리 2초) → ④ 본 트랜잭션.
실패 응답은 하나다 — 없는 이메일·틀린 비밀번호·탈퇴 회원의 상태 코드·본문이 같고, 없는 이메일도 가짜 해시로 검증해 시간을 맞춘다.
토큰(session_token·device_token·consent_token)은 응답 본문으로 Next 서버에만 돌려준다. 로그에 남기지 않는다.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import exists, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.auth import keys, sessions
from app.auth.emails import normalize_email
from app.auth.passwords import hash_password, needs_rehash, verify_password
from app.core import rate_limit
from app.core.problems import Problem
from app.core.threads import SlotTimeout, run_in_thread_within
from app.models import Member, PrivacyNotice

# 없는 이메일에도 같은 시간이 들도록 검증할 해시(아무 비밀번호의 argon2id — 기본 매개변수와 같아야 시간이 같다)
DUMMY_HASH = "$argon2id$v=19$m=65536,t=3,p=4$BNWPLOEcUbPWwKcq2CQ5QQ$CNozV3tOpsoIATWNPH0NPvcMyoAyvrJyys3K+wWKMQk"
ARGON2_WAIT = 2.0  # 한도 자리 얻기 기한(§7.7)


def login_failed() -> Problem:
    return Problem(401, "login_failed", "이메일 또는 비밀번호가 맞지 않습니다")


async def _argon2[T](fn, *args) -> T:
    try:
        return await run_in_thread_within("argon2", ARGON2_WAIT, fn, *args)
    except SlotTimeout:
        raise Problem(
            429, "busy", "로그인 요청이 많습니다. 잠시 뒤에 다시 시도해 주세요", headers={"Retry-After": "2"}
        ) from None


async def count_login(email: str, ip: str, device: str | None) -> None:
    """② 해시 전에 센다(§4.3-2·§4.3.1). 유효한 기기 쿠키면 이메일 단독 대신 쿠키 단위로 센다"""
    eh = keys.email_hmac(email).hex()
    await rate_limit.hit("auth.login", f"{eh}:{ip}")
    signature = keys.device_matches(device, email)
    if signature:
        await rate_limit.hit("auth.login_device", signature)
    else:
        await rate_limit.hit("auth.login_account", eh)
    await rate_limit.hit("auth.login_ip", ip)


async def needs_reconsent(db: AsyncSession, member: Member) -> bool:
    """회원이 동의한 판보다 새로 게시된 판 가운데 재동의가 필요한 판이 있는가(§3.6)"""
    agreed = aliased(PrivacyNotice)
    newer = select(agreed.published_at).where(agreed.version == member.privacy_version).scalar_subquery()
    stmt = select(
        exists().where(
            PrivacyNotice.published_at.is_not(None),
            PrivacyNotice.requires_reconsent.is_(True),
            PrivacyNotice.published_at > newer,
        )
    )
    return bool((await db.execute(stmt)).scalar_one())


async def start_session(db: AsyncSession, member: Member, persistent: bool, user_agent: str | None) -> dict[str, Any]:
    """세션 발급(+ 유지면 기기 쿠키) — 로그인과 재동의가 같은 함수를 쓴다"""
    token, expires_at = await sessions.issue(db, member, persistent, user_agent)
    member.last_login_at = datetime.now(UTC)
    notices = []
    if member.password_reset_by_admin_at is not None:  # 운영자 링크로 바뀌었다는 안내 — 한 번 보이고 지운다(§4.3-9)
        notices.append("password_reset_by_admin")
        member.password_reset_by_admin_at = None
    await db.flush()
    return {
        "session_token": token,
        # 유지 안 함이면 브라우저 세션 쿠키(Expires 없음) — 서버 만료는 따로 12시간
        "session_expires_at": expires_at.isoformat() if persistent else None,
        "device_token": keys.device_token(member.email or "") if persistent else None,
        "notices": notices,
    }


async def login(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    persistent: bool,
    ip: str,
    session_token: str | None,
    device_token: str | None,
    user_agent: str | None,
) -> dict[str, Any]:
    email = normalize_email(email)
    await count_login(email, ip, device_token)
    member = (await db.execute(select(Member).where(Member.email == email))).scalar_one_or_none()
    stored = member.password_hash if member is not None and member.password_hash else DUMMY_HASH
    ok = await _argon2(verify_password, stored, password)
    if member is None or not ok:
        raise login_failed()
    if member.status == "pending":  # 비밀번호가 맞을 때만 알려 준다(§4.3-5)
        raise Problem(403, "signup_pending", "가입 승인을 기다리고 있습니다. 승인되면 로그인할 수 있습니다")
    if member.status != "active":
        raise login_failed()
    if needs_rehash(stored):
        member.password_hash = await _argon2(hash_password, password)
    if session_token:  # 이 브라우저의 이전 세션
        await sessions.revoke_token(db, session_token)
    if await needs_reconsent(db, member):
        await db.flush()
        return {"consent_token": keys.consent_token(member.id, persistent)}
    return await start_session(db, member, persistent, user_agent)


async def consent(db: AsyncSession, *, token: str, user_agent: str | None) -> dict[str, Any]:
    """재동의(§3.6) — 최신 게시 판에 동의를 기록하고 그때 세션을 발급한다"""
    read = keys.read_consent_token(token)
    if read is None:
        raise Problem(401, "consent_expired", "동의 시간이 지났습니다. 다시 로그인해 주세요")
    member_id, persistent = read
    member = (
        await db.execute(
            select(Member).where(Member.id == member_id, Member.status == literal_column("'active'")).with_for_update()
        )
    ).scalar_one_or_none()
    # 잠근 뒤 다시 본다 — 동의가 기록되는 순간 조건이 사라지므로 같은 토큰은 한 번만 효과가 있다(재사용 = 세션 반복 발급 방지)
    if member is None or not await needs_reconsent(db, member):
        raise Problem(401, "consent_expired", "동의 시간이 지났습니다. 다시 로그인해 주세요")
    latest = await latest_notice(db)
    if latest is None:
        raise Problem(409, "no_privacy_notice", "게시된 개인정보 고지가 없습니다")
    member.privacy_version = latest.version
    member.privacy_agreed_at = datetime.now(UTC)
    return await start_session(db, member, persistent, user_agent)


async def latest_notice(db: AsyncSession) -> PrivacyNotice | None:
    return (
        await db.execute(
            select(PrivacyNotice)
            .where(PrivacyNotice.published_at.is_not(None))
            .order_by(PrivacyNotice.published_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
