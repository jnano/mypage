"""인증 정리 작업·운영 기록 가림 확장 — 인증 설계도 §8·§3.8"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LoginSession, Member, ModerationLog, PasswordResetToken, WithdrawnEmailMark
from app.worker import jobs
from tests.factories import make_member

pytestmark = pytest.mark.anyio
NOW = datetime.now(UTC)


async def test_cleanup_sessions_and_reset_tokens(db: AsyncSession) -> None:
    m = await make_member(db)
    db.add_all(
        [
            LoginSession(token_hash=b"a" * 32, member_id=m.id, expires_at=NOW - timedelta(days=8), persistent=False),  # 만료 8일
            LoginSession(token_hash=b"b" * 32, member_id=m.id, expires_at=NOW + timedelta(days=1), persistent=False, revoked_at=NOW - timedelta(days=8)),
            LoginSession(token_hash=b"c" * 32, member_id=m.id, expires_at=NOW - timedelta(days=1), persistent=False),  # 만료 1일 — 남김
            LoginSession(token_hash=b"d" * 32, member_id=m.id, expires_at=NOW + timedelta(days=1), persistent=True),  # 살아 있음
            PasswordResetToken(token_hash=b"r" * 32, member_id=m.id, expires_at=NOW + timedelta(hours=1), used_at=NOW),
            PasswordResetToken(token_hash=b"s" * 32, member_id=m.id, expires_at=NOW - timedelta(seconds=1)),
            PasswordResetToken(token_hash=b"t" * 32, member_id=m.id, expires_at=NOW + timedelta(hours=1)),
        ]
    )
    await db.flush()
    assert await jobs.cleanup_sessions(db) == 2
    assert {s for s in (await db.execute(select(LoginSession.token_hash))).scalars()} == {b"c" * 32, b"d" * 32}
    assert await jobs.cleanup_reset_tokens(db) == 2
    assert (await db.execute(select(PasswordResetToken.token_hash))).scalars().all() == [b"t" * 32]


async def test_cleanup_pending_and_marks(db: AsyncSession) -> None:
    old = await make_member(db, status="pending")
    fresh = await make_member(db, status="pending")
    await db.execute(update(Member).where(Member.id == old.id).values(created_at=NOW - timedelta(days=31)))
    db.add_all(
        [
            WithdrawnEmailMark(email_hmac=b"x" * 32, expires_at=NOW - timedelta(seconds=1)),
            WithdrawnEmailMark(email_hmac=b"y" * 32, expires_at=NOW + timedelta(days=1)),
        ]
    )
    await db.flush()
    assert await jobs.cleanup_pending_signups(db) == 1
    assert (await db.execute(select(Member.id).where(Member.status == "pending"))).scalars().all() == [fresh.id]
    assert await jobs.cleanup_withdrawn_marks(db) == 1


async def test_redact_member_target_logs_but_not_same_numbered_group(db: AsyncSession) -> None:
    gone = await make_member(db, status="withdrawn", withdrawn_at=NOW)
    db.add_all(
        [
            ModerationLog(action="member.approve", target_type="member", target_id=gone.id, after={"email": "a***@b***.com", "display_name": "이름"}),
            ModerationLog(action="group.create", target_type="group", target_id=gone.id, after={"name": "모임"}),
        ]
    )
    await db.flush()
    assert await jobs.redact_moderation_logs(db) == 1
    rows = {r.action: r for r in (await db.execute(select(ModerationLog))).scalars()}
    assert rows["member.approve"].after == {"email": "[가림]", "display_name": "[가림]"} and rows["member.approve"].redacted_at
    assert rows["group.create"].redacted_at is None


def test_jobs_registered() -> None:
    assert {"sessions.cleanup", "reset_tokens.cleanup", "pending_signups.cleanup", "withdrawn_marks.cleanup"} <= set(jobs.JOBS)
