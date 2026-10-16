"""인증 경보 — 인증 설계도 §7.5. 막지 않고 운영자가 알게 한다(운영 기록 + 대시보드 '경보' 배지).

창(분·시간)마다 한도를 **처음 넘는 순간** 한 줄만 남긴다. 본 요청이 실패로 되돌려져도 남도록 별도 커밋.
"""

from datetime import UTC, datetime

from app.admin.logs import LogEntry, record
from app.auth.viewer import GUEST
from app.core import rate_limit
from app.core.rate_limit import Limit
from app.db.session import SessionLocal


async def _alert(action: str, limit: Limit, start: float) -> None:
    async with SessionLocal() as db, db.begin():
        await record(
            db,
            GUEST,  # 행위자 없음(시스템)
            [
                LogEntry(
                    action, "setting", 0,
                    after={"window_start": datetime.fromtimestamp(start, UTC).isoformat(), "limit": limit.count, "window_sec": limit.window_sec},
                )
            ],
        )  # fmt: skip


async def login_failed() -> None:
    """로그인 실패 한 번 — 사이트 전체 분당 기준을 처음 넘으면 경보"""
    n, limit, start = await rate_limit.tally("auth.login_failed_site", "site")
    if n == limit.count + 1:
        await _alert("alert.login_failures", limit, start)


async def signup_received(hourly_limit: int) -> None:
    """가입 접수 한 번 — 사이트 전체 시간당 상한을 넘으면 429, 처음 넘는 순간 경보(공격자가 접수를 끌 수 있음을 운영자가 알게)"""
    n, limit, start = await rate_limit.tally("auth.signup_all", "site", count=hourly_limit)
    if n > limit.count:
        if n == limit.count + 1:
            await _alert("alert.signup_cap", limit, start)
        raise rate_limit.exceeded(limit, start)
