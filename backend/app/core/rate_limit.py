"""요청 수 제한 — 설계도 §6. PostgreSQL UNLOGGED 고정 창(rate_limit_counters).

확인·증가는 본 트랜잭션과 분리된 짧은 트랜잭션이다 — 본 트랜잭션이 실패해도 시도 횟수는 남는다.
메모리 저장소는 프로세스 수만큼 한도가 늘어나 쓰지 않는다.
"""

import logging
import math
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert

from app.core.problems import Problem
from app.db.session import SessionLocal
from app.models import RateLimitCounter

logger = logging.getLogger(__name__)


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
    "upload": Limit(30, 60),
    "site.design": Limit(30, 60),  # 운영자의 틀·페이지·메뉴·블록 저장(홈블록 §7) — 회원 id
    "editor.preview": Limit(60, 60),
    "report.create": Limit(10, 600),
    "search": Limit(30, 60),  # 회원 id 또는 비회원 client_ip()(§6.3)
    # 인증(인증 설계도 §7.5) — IP 는 client_ip(), 이메일은 HMAC(원문을 키에 넣지 않는다). 검증 전에 세므로 성공도 센다
    "auth.login": Limit(10, 900),  # 이메일 + IP
    "auth.login_account": Limit(100, 900),  # 이메일 단독 — 이 이메일의 유효한 기기 쿠키면 건너뛴다
    "auth.login_device": Limit(10, 900),  # 기기 쿠키로 면제받은 요청(쿠키 서명 값 기준)
    "auth.login_ip": Limit(60, 900),  # IP 단독 — 이동통신·회사망은 많은 사람이 IP 하나를 쓴다
    "auth.signup": Limit(5, 3600),  # IP
    "auth.signup_all": Limit(20, 3600),  # 사이트 전체 — 횟수는 설정 signup.hourly_limit 이 정한다(count 인자)
    # 사이트 전체 로그인 실패 — 막지 않고 경보만(§7.5). 분당 이 수를 처음 넘는 순간 운영 기록 한 줄
    "auth.login_failed_site": Limit(100, 60),  # 사이트 전체
    "auth.reset": Limit(10, 900),
    "auth.reauth": Limit(5, 900),
    "level.request": Limit(3, 86400),
    # 글 반응(§6.1) — 시작값. 넘은 흔적이 남지 않으므로 창마다 처음 넘는 순간 경고 로그(WARN_ON_EXCEED)
    "post.react": Limit(60, 60),  # 회원 id — 추천·스크랩 켜기·끄기
    "post.view": Limit(60, 60),  # client_ip() — 조회 신호
    "post.share": Limit(3, 3600),  # client_ip() + 글 id — 공유. 넘으면 세지 않는다
    # 비회원 글쓰기(§6.3) — 시도(성공·실패 모두, 맨 앞)·성공·사이트 전체(경보)·수정, 비회원 토큰(IP·글 + 글 전체)
    "post.create_guest_attempt": Limit(20, 600),
    "post.create_guest": Limit(3, 600),
    "post.create_guest_all": Limit(60, 3600),
    "post.update_guest": Limit(5, 600),
    "guest.token": Limit(5, 600),
    "guest.token_post": Limit(50, 600),
}

# 넘어도 운영 기록이 남지 않는 키 — 한도 값을 나중에 다시 보려고 창마다 처음 넘는 순간 로그 한 줄(키 종류·한도만, 주체 원문 없음)
WARN_ON_EXCEED = frozenset({"post.react", "post.view", "post.share", "post.create_guest_attempt", "post.create_guest", "post.update_guest", "guest.token", "guest.token_post"})


async def tally(action: str, subject: str, count: int | None = None) -> tuple[int, Limit, float]:
    """한 번 세고 (지금 창의 횟수, 한도, 창 시작 시각)을 돌려준다 — 막지 않는다(경보 판정용)."""
    limit = LIMITS[action] if count is None else Limit(count, LIMITS[action].window_sec)
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
        n = (await db.execute(stmt)).scalar_one()
        await db.commit()
    return n, limit, start


def exceeded(limit: Limit, start: float) -> Problem:
    retry_after = max(1, math.ceil(start + limit.window_sec - time.time()))
    return Problem(
        429,
        "rate_limited",
        "요청이 너무 많습니다. 잠시 뒤에 다시 시도해 주세요",
        headers={"Retry-After": str(retry_after)},
    )


async def hit(action: str, subject: str, count: int | None = None) -> int:
    """한 번 센다. 한도를 넘으면 429 + Retry-After. count 는 설정값으로 정하는 한도(창 길이는 LIMITS 그대로).
    돌려주는 값은 지금 창의 횟수."""
    n, limit, start = await tally(action, subject, count)
    if n > limit.count:
        _warn_first(action, n, limit)
        raise exceeded(limit, start)
    return n


async def allow(action: str, subject: str) -> bool:
    """한 번 세고 한도 안인지 — 넘어도 예외 없이 '세지 않음'으로 끝낼 곳(조회·공유 카운터)"""
    n, limit, _ = await tally(action, subject)
    if n > limit.count:
        _warn_first(action, n, limit)
        return False
    return True


def _warn_first(action: str, n: int, limit: Limit) -> None:
    if action in WARN_ON_EXCEED and n == limit.count + 1:
        logger.warning("요청 수 한도를 넘음: %s (한도 %d회/%d초)", action, limit.count, limit.window_sec)
