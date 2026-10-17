"""검색어 집계와 인기 검색어 — 설계도 §9.1.

검색 요청은 (키, 보여 줄 꼴, 사람)을 이 프로세스 메모리에 넣고 끝난다. lifespan 배경 작업이 5초마다 한 트랜잭션으로 반영한다:
사람 해시(날짜별 키 = HMAC(subkey("search"), 사이트 날짜) — DB 만 읽어서는 되맞출 수 없다)를 search_term_searchers 에 넣어
새 사람·새 회원 수를 얻고 → search_term_daily·search_terms 에 더한다. 사람 해시는 날짜가 바뀐 뒤 한 시간 안에 지운다.
인기 검색어: 최근 7일 가운데 '그날 서로 다른 사람 ≥ 문턱 ∧ 그 가운데 회원 ≥ 1' 인 날이 이틀 이상인 키만, 검색 수 순으로(사용자 결정).
후보 50개는 작업자가 매시 search_popular 에 다시 만든다(요청마다 7일치를 모으면 p95 167ms — 측정).
"""

import asyncio
import base64
import hashlib
import hmac
import logging
import re
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import aggregate_order_by, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin import settings as site_settings
from app.admin.settings import SearchSettings, SpamPolicy
from app.auth.viewer import Viewer
from app.db.session import SessionLocal
from app.auth.keys import subkey
from app.models import SearchPopular, SearchTerm, SearchTermDaily, SearchTermSearcher
from app.core.site_date import site_today
from app.search.index import compact

logger = logging.getLogger(__name__)

INTERVAL_SEC = 5
SAME_PERSON_SEC = 30
MAX_BATCH = 10_000  # 넘으면 그 뒤는 버린다 — 폭주가 메모리를 키우지 않게
MAX_ATTEMPTS = 3
POPULAR_DAYS = 7
POPULAR_LIMIT = 10
POPULAR_SCAN = 50  # 거른 뒤 10개가 되도록 앞에서 이만큼 읽는다
POPULAR_MIN_DAYS = 2  # 문턱을 넘은 날이 기간 안에 이만큼 — 하루 몰아치기로는 오르지 않는다(사용자 결정)
MEMBER_PREFIX = "m:"
DISPLAY_LEN = 100
_SPACES = re.compile(r"\s+")


@dataclass(frozen=True)
class Hit:
    term: str
    display: str
    searcher: str


_pending: list[Hit] = []
_recent: dict[tuple[str, str], float] = {}
_attempts = 0
_overflow_warned = False


def display_form(raw: str) -> str:
    return _SPACES.sub(" ", unicodedata.normalize("NFKC", raw)).strip()[:DISPLAY_LEN]


def searcher_of(viewer: Viewer, ip: str) -> str:
    """회원 m:{id}, 비회원 ip:{client_ip} — IP 하나를 여럿이 쓰면 한 사람(적게 세는 쪽, §9.1)"""
    return f"m:{viewer.member_id}" if viewer.member_id is not None else f"ip:{ip}"


def record(term: str, raw: str, searcher: str, *, now: float | None = None) -> bool:
    """한 번 넣는다. 같은 사람·같은 키는 30초 안에 다시 넣지 않는다(프로세스마다). 넣었으면 True"""
    global _overflow_warned
    at = time.monotonic() if now is None else now
    key = (term, searcher)
    last = _recent.get(key)
    if last is not None and at - last < SAME_PERSON_SEC:
        return False
    if len(_pending) >= MAX_BATCH:
        if not _overflow_warned:
            logger.warning("검색어 집계 묶음이 %d줄을 넘어 그 뒤를 버립니다", MAX_BATCH)
            _overflow_warned = True
        return False
    _recent[key] = at
    _pending.append(Hit(term, display_form(raw), searcher))
    return True


def _forget_old(now: float) -> None:
    for key in [k for k, at in _recent.items() if now - at >= SAME_PERSON_SEC]:
        del _recent[key]


def day_key(day) -> bytes:
    """날짜별 키 — 비밀(EMAIL_HMAC_SECRET 의 용도별 파생 키)에서 만든다. 표에 두지 않는다(검토 v4.0.12 N-1)"""
    return hmac.new(subkey("search"), day.isoformat().encode(), hashlib.sha256).digest()


def _hash(key: bytes, searcher: str) -> str:
    """앞 22자 = 132비트 — 하루 안 사람 수(많아야 수만)에서 겹칠 걱정이 없다"""
    return base64.urlsafe_b64encode(hmac.new(key, searcher.encode(), hashlib.sha256).digest()).decode()[:22]


async def _apply(batch: list[Hit]) -> None:
    async with SessionLocal() as db, db.begin():
        day = (await db.execute(select(site_today()))).scalar_one()
        key = day_key(day)
        searches = Counter(h.term for h in batch)
        display: dict[str, str] = {}
        for h in batch:  # 처음 꼴 — 한 사람이 보여 줄 글자를 바꾸지 못하게(검토 v4.0.12 N-3)
            display.setdefault(h.term, h.display)
        is_member = {}
        for h in batch:
            is_member[(h.term, _hash(key, h.searcher))] = h.searcher.startswith(MEMBER_PREFIX)
        new_people: Counter[str] = Counter()
        new_members: Counter[str] = Counter()
        rows = sorted(is_member)
        if rows:
            stmt = (
                insert(SearchTermSearcher)
                .values([{"day": day, "term": t, "searcher": s} for t, s in rows])
                .on_conflict_do_nothing()
                .returning(SearchTermSearcher.term, SearchTermSearcher.searcher)
            )
            for term, searcher in await db.execute(stmt):
                new_people[term] += 1
                if is_member[(term, searcher)]:
                    new_members[term] += 1
        terms = sorted(searches)  # 키 순서 — 여러 프로세스가 같은 행을 같은 순서로 잠근다
        daily = insert(SearchTermDaily).values(
            [
                {"day": day, "term": t, "display": display[t], "searches": searches[t], "people": new_people[t], "members": new_members[t]}
                for t in terms
            ]
        )
        await db.execute(
            daily.on_conflict_do_update(
                index_elements=["day", "term"],
                set_={  # display 는 그날 처음 꼴 그대로
                    "searches": SearchTermDaily.searches + daily.excluded.searches,
                    "people": SearchTermDaily.people + daily.excluded.people,
                    "members": SearchTermDaily.members + daily.excluded.members,
                },
            )
        )
        total = insert(SearchTerm).values([{"term": t, "count": searches[t], "last_searched_at": func.now()} for t in terms])
        await db.execute(
            total.on_conflict_do_update(
                index_elements=["term"],
                set_={"count": SearchTerm.count + total.excluded.count, "last_searched_at": total.excluded.last_searched_at},
            )
        )


async def flush() -> int:
    """묶음을 반영한다. 반영한 줄 수. 실패하면 되돌리고 MAX_ATTEMPTS 회 뒤 버린다, 취소되면 되돌리고 다시 올린다"""
    global _attempts, _overflow_warned
    _forget_old(time.monotonic())
    if not _pending:
        return 0
    batch = list(_pending)
    _pending.clear()
    _overflow_warned = False
    try:
        await _apply(batch)
    except BaseException as e:
        if not isinstance(e, Exception):
            _pending[:0] = batch
            raise
        _attempts += 1
        if _attempts >= MAX_ATTEMPTS:
            logger.warning("검색어 집계 반영이 %d번 실패해 %d줄을 버립니다", _attempts, len(batch))
            _attempts = 0
        else:
            logger.exception("검색어 집계 반영 실패 — 다음 차례에 다시")
            _pending[:0] = batch
        return 0
    _attempts = 0
    return len(batch)


async def run_forever() -> None:
    while True:
        await asyncio.sleep(INTERVAL_SEC)
        try:
            await flush()
        except Exception:
            logger.exception("검색어 집계 작업 오류")


def _excluded(term: str, banned: list[str], excluded: set[str]) -> bool:
    if term in excluded:
        return True
    return any(w and w in term for w in banned)


async def rebuild_popular(db: AsyncSession) -> int:
    """인기 후보를 다시 만든다 — 작업자 search_terms.popular(매시). 최근 7일 가운데 '그날 서로 다른 사람 ≥ 문턱 ∧ 회원 ≥ 1'인
    날이 이틀 이상인 키를 검색 수 순으로 위 50개. 거르기(금지어·검색 제외)는 읽을 때 한다 — 설정을 바꾸면 바로 반영되게"""
    search = await site_settings.load(db, "search")
    assert isinstance(search, SearchSettings)
    since = site_today() - (POPULAR_DAYS - 1)
    stmt = (
        select(
            SearchTermDaily.term,
            # 가장 최근 날의 보여 줄 꼴(그날 처음 꼴)
            func.array_agg(aggregate_order_by(SearchTermDaily.display, SearchTermDaily.day.desc()))[1].label("display"),
        )
        .where(SearchTermDaily.day >= since)
        .group_by(SearchTermDaily.term)
        .having(
            func.count()
            .filter((SearchTermDaily.people >= search.popular_min_people) & (SearchTermDaily.members >= 1))
            >= POPULAR_MIN_DAYS
        )
        .order_by(func.sum(SearchTermDaily.searches).desc(), SearchTermDaily.term)
        .limit(POPULAR_SCAN)
    )
    rows = list(await db.execute(stmt))
    await db.execute(delete(SearchPopular))
    if rows:
        await db.execute(insert(SearchPopular).values([{"rank": i, "term": r.term, "display": r.display} for i, r in enumerate(rows, 1)]))
    return len(rows)


async def popular(db: AsyncSession, search: SearchSettings) -> list[dict]:
    """쿼리 2(스팸 설정 1·후보 1) — 검색 설정은 호출부가 읽어 넘긴다. 후보는 작업자가 매시 만든 50개"""
    spam = await site_settings.load(db, "spam")
    assert isinstance(spam, SpamPolicy)
    banned = [compact(w) for w in spam.banned_words]
    excluded = {compact(w) for w in search.excluded_terms}
    out = []
    for r in await db.execute(select(SearchPopular.term, SearchPopular.display).order_by(SearchPopular.rank)):
        if not _excluded(r.term, banned, excluded):
            out.append({"term": r.term, "display": r.display})
        if len(out) == POPULAR_LIMIT:
            break
    return out
