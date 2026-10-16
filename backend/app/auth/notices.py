"""개인정보 고지 판 관리(운영자) — 인증 설계도 §3.6. 게시한 판은 고치지 않는다(문구를 바꾸려면 새 판).

재동의가 필요한 판을 게시하면, 그 트랜잭션에서 그보다 오래된 판에 동의한 회원의 세션을 한 문장으로 모두 폐기한다
(이미 발급된 세션도 재동의 없이 쓰이지 않게, 검토 v2 C-2). 다음 로그인 때 재동의 화면으로 간다.
"""

import re
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.logs import LogEntry, record
from app.auth.viewer import Viewer
from app.core.problems import Problem
from app.models import LoginSession, Member, PrivacyNotice

_VERSION = re.compile(r"^[0-9A-Za-z._-]{1,20}$")


class NoticeDraft(BaseModel):
    version: str = Field(max_length=20)
    body: str = Field(min_length=1, max_length=50_000)
    requires_reconsent: bool = False

    @field_validator("version")
    @classmethod
    def _version(cls, v: str) -> str:
        if not _VERSION.match(v):
            raise ValueError("판 이름은 영문·숫자·.·_·- 20자까지입니다(예: 2026-10-16)")
        return v


class NoticeUpdate(BaseModel):
    body: str | None = Field(default=None, min_length=1, max_length=50_000)
    requires_reconsent: bool | None = None


def _row(n: PrivacyNotice) -> dict[str, Any]:
    return {
        "version": n.version,
        "body": n.body,
        "requires_reconsent": n.requires_reconsent,
        "published_at": n.published_at.isoformat() if n.published_at else None,
    }


async def list_notices(db: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(PrivacyNotice).order_by(PrivacyNotice.published_at.desc().nulls_first(), PrivacyNotice.version.desc())
        )
    ).scalars()
    return [_row(n) for n in rows]


async def create_draft(db: AsyncSession, viewer: Viewer, draft: NoticeDraft) -> dict[str, Any]:
    notice = PrivacyNotice(
        version=draft.version, body=draft.body, requires_reconsent=draft.requires_reconsent, created_by=viewer.member_id
    )
    db.add(notice)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise Problem(409, "notice_exists", "같은 이름의 판이 있습니다") from None
    await record(db, viewer, [LogEntry("privacy_notice.create", "setting", 0, after={"version": draft.version})])
    return _row(notice)


async def _draft(db: AsyncSession, version: str) -> PrivacyNotice:
    notice = (
        await db.execute(select(PrivacyNotice).where(PrivacyNotice.version == version).with_for_update())
    ).scalar_one_or_none()
    if notice is None:
        raise Problem(404, "notice_not_found", "그 판이 없습니다")
    if notice.published_at is not None:
        raise Problem(409, "notice_published", "게시한 판은 고칠 수 없습니다 — 새 판을 만들어 주세요")
    return notice


async def update_draft(db: AsyncSession, viewer: Viewer, version: str, patch: NoticeUpdate) -> dict[str, Any]:
    notice = await _draft(db, version)
    if patch.body is not None:
        notice.body = patch.body
    if patch.requires_reconsent is not None:
        notice.requires_reconsent = patch.requires_reconsent
    await db.flush()
    return _row(notice)


async def publish(db: AsyncSession, viewer: Viewer, version: str) -> dict[str, Any]:
    notice = await _draft(db, version)
    now = datetime.now(UTC)
    notice.published_at = now
    revoked = 0
    if notice.requires_reconsent:
        agreed_at = (
            select(PrivacyNotice.published_at).where(PrivacyNotice.version == Member.privacy_version).scalar_subquery()
        )
        stale = select(Member.id).where(agreed_at < now)
        result = await db.execute(
            update(LoginSession)
            .where(LoginSession.revoked_at.is_(None), LoginSession.member_id.in_(stale))
            .values(revoked_at=now)
        )
        revoked = result.rowcount or 0
    await db.flush()
    await record(
        db,
        viewer,
        [
            LogEntry(
                "privacy_notice.publish", "setting", 0,
                after={"version": version, "requires_reconsent": notice.requires_reconsent, "sessions_revoked": revoked},
            )
        ],
    )  # fmt: skip
    return _row(notice) | {"sessions_revoked": revoked}
