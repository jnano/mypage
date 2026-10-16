"""세션 — 인증 설계도 §3.2·§4.3-6·§4.5. 토큰 원문은 Next 쿠키에만 있고 DB 에는 SHA-256 만 둔다."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import LoginSession, Member


def hash_token(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def lifetime(is_admin: bool, persistent: bool) -> timedelta:
    """§3.2.1 — 유지 안 함 12시간, 유지 + 회원 30일, 유지 + 운영자 7일"""
    if not persistent:
        return timedelta(hours=settings.session_hours)
    return timedelta(days=settings.session_admin_days if is_admin else settings.session_member_days)


async def issue(db: AsyncSession, member: Member, persistent: bool, user_agent: str | None) -> tuple[str, datetime]:
    """새 세션(로그인마다 새 토큰) — 토큰 원문과 만료 시각"""
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    expires_at = now + lifetime(member.is_admin, persistent)
    db.add(
        LoginSession(
            token_hash=hash_token(token),
            member_id=member.id,
            expires_at=expires_at,
            persistent=persistent,
            user_agent=(user_agent or "")[:200] or None,
            created_at=now,
            last_write_at=now,
        )
    )
    await db.flush()
    return token, expires_at


async def revoke_token(db: AsyncSession, token: str) -> int | None:
    """이 토큰의 세션을 폐기 — 폐기한 세션의 회원 id(없으면 None)"""
    result = await db.execute(
        update(LoginSession)
        .where(LoginSession.token_hash == hash_token(token), LoginSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
        .returning(LoginSession.member_id)
    )
    return result.scalar_one_or_none()


async def revoke_all(db: AsyncSession, member_id: int, except_id: int | None = None) -> None:
    stmt = update(LoginSession).where(LoginSession.member_id == member_id, LoginSession.revoked_at.is_(None))
    if except_id is not None:
        stmt = stmt.where(LoginSession.id != except_id)
    await db.execute(stmt.values(revoked_at=datetime.now(UTC)))
