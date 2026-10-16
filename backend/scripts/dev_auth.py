"""개발·측정 DB 의 인증 칸 공용 값 — 시드(seed_dev·seed_posts)와 채움 스크립트(fill_auth_dev)가 함께 쓴다.

개발용 비밀번호는 backend/README.md '개발' 에 적혀 있다. 운영에서 쓰지 않는다.
"""

from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PrivacyNotice

DEV_PASSWORD = "dev-password-0123456789"
DEV_NOTICE = "dev-notice"


async def ensure_dev_notice(db: AsyncSession) -> str:
    """개발·측정용 고지 판 하나(게시됨, 재동의 불필요). 이미 있으면 그대로"""
    await db.execute(
        insert(PrivacyNotice)
        .values(
            version=DEV_NOTICE,
            body="개발·측정용 개인정보 고지입니다. 운영에서는 첫 운영자 CLI 가 실제 고지문으로 첫 판을 만듭니다.",
            requires_reconsent=False,
            published_at=datetime.now(UTC),
        )
        .on_conflict_do_nothing()
    )
    return DEV_NOTICE
