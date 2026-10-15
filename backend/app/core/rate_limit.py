"""요청 수 제한 — 설계도 §6. PostgreSQL UNLOGGED 고정 창(rate_limit_counters).

확인·증가는 본 트랜잭션과 분리된 짧은 트랜잭션이다 — 본 트랜잭션이 실패해도 시도 횟수는 남는다.
메모리 저장소는 프로세스 수만큼 한도가 늘어나 쓰지 않는다.
"""

import math
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert

from app.core.problems import Problem
from app.db.session import SessionLocal
from app.models import RateLimitCounter


@dataclass(frozen=True)
class Limit:
    count: int
    window_sec: int


# 행동 → 한도. 값은 운영하며 조정한다
LIMITS: dict[str, Limit] = {
    "post.create": Limit(10, 60),
    "post.update": Limit(30, 60),
    "comment.create": Limit(20, 60),
    "comment.update": Limit(30, 60),
    "editor.preview": Limit(60, 60),
    # 비회원 검색은 실제 IP 를 믿을 수 있는 배포 구성(§17 nginx real_ip) 뒤에 붙인다
    "search": Limit(30, 60),
}


async def hit(action: str, subject: str) -> None:
    """한 번 센다. 한도를 넘으면 429 + Retry-After."""
    limit = LIMITS[action]
    now = time.time()
    start = math.floor(now / limit.window_sec) * limit.window_sec
    stmt = (
        insert(RateLimitCounter)
        .values(
            key=f"{action}:{subject}",
            window_start=datetime.fromtimestamp(start, UTC),
            count=1,
        )
        .on_conflict_do_update(
            index_elements=["key", "window_start"],
            set_={"count": RateLimitCounter.count + 1},
        )
        .returning(RateLimitCounter.count)
    )
    async with SessionLocal() as db:
        count = (await db.execute(stmt)).scalar_one()
        await db.commit()
    if count > limit.count:
        retry_after = max(1, math.ceil(start + limit.window_sec - now))
        raise Problem(
            429,
            "rate_limited",
            "요청이 너무 많습니다. 잠시 뒤에 다시 시도해 주세요",
            headers={"Retry-After": str(retry_after)},
        )
