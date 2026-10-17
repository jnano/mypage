"""검색어 집계·인기·추천 검색어 — 설계도 §9.1."""

import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import SearchTerm, SearchTermDaily, SearchTermSearcher, SiteSetting
from app.search import terms
from app.worker import jobs
from tests.factories import make_board, make_member, make_post
from tests.helpers import as_member

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _clean_memory():
    terms._pending.clear()
    terms._recent.clear()
    yield
    terms._pending.clear()
    terms._recent.clear()


def _today():
    return datetime.now(ZoneInfo(settings.site_time_zone)).date()


async def _daily(db: AsyncSession) -> dict[str, tuple[int, int, str]]:
    db.expire_all()
    async with SessionLocal() as s:
        return {r.term: (r.searches, r.people, r.display, r.members) for r in (await s.execute(select(SearchTermDaily))).scalars()}


async def _search(client, q: str, *, ip: str = "203.0.113.5", member: int | None = None, page: int = 1):
    headers = {"X-Client-IP": ip} | (as_member(member) if member else {})
    return await client.get("/api/search", params={"q": q, "page": page}, headers=headers)


# ── 세는 것 ─────────────────────────────────────────────


async def test_counts_first_page_once_per_person(dev_header, committed_db, client) -> None:
    board = await make_board(committed_db, slug="free")
    member = await make_member(committed_db, level=1)
    await make_post(committed_db, board, member, title="회의 자료")
    await committed_db.commit()
    assert (await _search(client, "회의 자료")).status_code == 200
    await _search(client, "회의자료")  # 띄어쓰기 변형 — 같은 키, 같은 사람(IP) 30초 안
    await _search(client, "회의 자료", ip="203.0.113.6")  # 다른 비회원
    await _search(client, "회의 자료", member=member.id)  # 회원
    await _search(client, "회의 자료", ip="203.0.113.7", page=2)  # 둘째 쪽은 세지 않는다
    assert (await _search(client, "회")).status_code == 422  # 검증 실패는 세지 않는다
    assert [h.searcher for h in terms._pending] == ["ip:203.0.113.5", "ip:203.0.113.6", f"m:{member.id}"]
    assert await terms.flush() == 3
    daily = await _daily(committed_db)
    assert daily == {"회의자료": (3, 3, "회의 자료", 1)}  # 보여 줄 꼴은 처음 꼴, 회원 1
    total = (await committed_db.execute(select(SearchTerm.count).where(SearchTerm.term == "회의자료"))).scalar_one()
    assert total == 3


def test_same_person_window_and_overflow(monkeypatch) -> None:
    assert terms.record("회의", "회의", "m:1", now=100.0)
    assert not terms.record("회의", "회의", "m:1", now=129.0)
    assert terms.record("회의", "회의", "m:1", now=130.0)  # 30초 뒤에는 다시
    assert terms.record("회의", "회의", "m:2", now=130.0)
    monkeypatch.setattr(terms, "MAX_BATCH", 3)
    assert not terms.record("안내", "안내", "m:3", now=131.0)  # 묶음 상한
    assert len(terms._pending) == 3


def test_display_form() -> None:
    assert terms.display_form("  회의\t　자료  ") == "회의 자료"
    assert terms.display_form("ＡＢＣ") == "ABC"
    assert len(terms.display_form("가" * 300)) == terms.DISPLAY_LEN


# ── 반영 ─────────────────────────────────────────────────


async def test_people_counted_once_across_flushes(committed_db) -> None:
    """다른 프로세스·다른 묶음에서 같은 사람이 다시 와도 people 은 한 번(그날의 해시가 같다)"""
    terms.record("안내", "안내", "m:7", now=0.0)
    terms.record("안내", "안내", "m:8", now=0.0)
    await terms.flush()
    terms._recent.clear()  # 다른 프로세스라 30초 기억이 없다
    terms.record("안내", "안내", "m:7", now=0.0)
    await terms.flush()
    assert (await _daily(committed_db))["안내"] == (3, 2, "안내", 2)
    hashes = list((await committed_db.execute(select(SearchTermSearcher.searcher))).scalars())
    assert len(hashes) == 2 and all(len(h) == 22 and not h.startswith("m:") for h in hashes)


async def test_concurrent_flushes_sum(committed_db) -> None:
    batch_a = [terms.Hit("모집", "모집", f"m:{i}") for i in range(10)]
    batch_b = [terms.Hit("모집", "모집", f"m:{i}") for i in range(5, 15)]
    await asyncio.gather(terms._apply(batch_a), terms._apply(batch_b))
    assert (await _daily(committed_db))["모집"][:2] == (20, 15)


async def test_first_display_wins_and_key_is_secret_derived(committed_db) -> None:
    terms.record("회의자료", "회의 자료", "ip:1.1.1.1", now=0.0)
    terms.record("회의자료", "회의  자료!!", "ip:2.2.2.2", now=0.0)
    await terms.flush()
    terms.record("회의자료", "다른 꼴", "ip:3.3.3.3", now=0.0)
    await terms.flush()
    assert (await _daily(committed_db))["회의자료"][2] == "회의 자료"
    # 날짜별 키는 비밀에서 — 날짜가 다르면 다르고, 같은 날은 같다
    today = _today()
    assert terms.day_key(today) == terms.day_key(today) != terms.day_key(today - timedelta(days=1))


async def test_flush_failure_and_cancel(monkeypatch) -> None:
    terms.record("공지", "공지", "m:1", now=0.0)

    async def broken(_batch):
        raise ConnectionError("DB 없음")

    monkeypatch.setattr(terms, "_apply", broken)
    assert await terms.flush() == 0 and len(terms._pending) == 1
    assert await terms.flush() == 0 and len(terms._pending) == 1
    assert await terms.flush() == 0 and terms._pending == []  # 3번째에 버림

    terms.record("공지", "공지", "m:2", now=100.0)

    async def hangs(_batch):
        await asyncio.sleep(10)

    monkeypatch.setattr(terms, "_apply", hangs)
    task = asyncio.create_task(terms.flush())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert [h.searcher for h in terms._pending] == ["m:2"]


# ── 인기·추천 ─────────────────────────────────────────────


async def _put_daily(db: AsyncSession, rows: list[tuple]) -> None:
    db.add_all([SearchTermDaily(day=d, term=t, display=t, searches=s, people=p, members=m) for d, t, s, p, m in rows])
    await db.commit()


async def _rebuild() -> int:
    """작업자 search_terms.popular 한 번"""
    async with SessionLocal() as s, s.begin():
        return await terms.rebuild_popular(s)


async def test_popular_threshold_window_and_filters(committed_db, client) -> None:
    today = _today()
    y = today - timedelta(days=1)
    await _put_daily(
        committed_db,
        [
            (today, "회의", 25, 5, 1), (y, "회의", 25, 5, 1),  # 이틀 문턱(5명·회원 1) — 나온다
            (today, "안내", 50, 4, 1), (y, "안내", 40, 4, 1),  # 4명 — 안 나온다
            (today - timedelta(days=3), "모집", 30, 6, 2), (today - timedelta(days=5), "모집", 10, 5, 1),  # 7일 안 이틀 — 나온다
            (today, "몰아치기", 900, 50, 3),  # 하루뿐 — 안 나온다
            (today, "비회원만", 80, 9, 0), (y, "비회원만", 80, 9, 0),  # 회원 0 — 안 나온다
            (today, "옛날", 1, 5, 1), (today - timedelta(days=7), "옛날", 999, 50, 9),  # 7일 밖 날은 세지 않는다
            (today, "광고문구", 80, 9, 1), (y, "광고문구", 80, 9, 1),  # 금지어 — 거른다
            (today, "홍길동", 70, 9, 1), (y, "홍길동", 70, 9, 1),  # 검색 제외 — 거른다
        ],
    )
    committed_db.add_all(
        [
            SiteSetting(key="spam", value={"banned_words": ["광고"]}),
            SiteSetting(key="search", value={"recommended": ["공지"], "excluded_terms": ["홍 길동"], "popular_min_people": 5}),
        ]
    )
    await committed_db.commit()
    assert await _rebuild() == 4  # 후보(거르기 전): 회의·모집·광고문구·홍길동
    res = await client.get("/api/search/terms")
    assert res.status_code == 200
    body = res.json()
    assert [p["term"] for p in body["popular"]] == ["회의", "모집"]  # 검색 수(50, 40) 순
    assert body["recommended"] == ["공지"]
    assert body["cache"]["tags"] == ["settings:search", "settings:spam"]


async def test_popular_defaults_and_query_budget(committed_db, client) -> None:
    from tests.helpers import count_queries

    today = _today()
    await _put_daily(committed_db, [(d, f"단어{i}", 100 - i, 5, 1) for i in range(15) for d in (today, today - timedelta(days=1))])
    await _rebuild()
    with count_queries() as q:
        body = (await client.get("/api/search/terms")).json()
    assert len(body["popular"]) == terms.POPULAR_LIMIT and body["recommended"] == []
    assert q["n"] <= 3, q["sql"]  # 검색 설정 1·스팸 설정 1·후보 1
    # 다시 만들면 이전 후보를 통째로 바꾼다
    await committed_db.execute(SearchTermDaily.__table__.delete())
    await committed_db.commit()
    assert await _rebuild() == 0
    assert (await client.get("/api/search/terms")).json()["popular"] == []


# ── 정리 ─────────────────────────────────────────────────


async def test_cleanup_drops_yesterday_people_keeps_counts(committed_db) -> None:
    today = _today()
    committed_db.add_all(
        [
            SearchTermSearcher(day=today - timedelta(days=1), term="회의", searcher="a" * 22),
            SearchTermSearcher(day=today, term="회의", searcher="b" * 22),
        ]
    )
    await _put_daily(committed_db, [(today - timedelta(days=1), "회의", 3, 3, 1), (today - timedelta(days=91), "회의", 1, 1, 0)])
    async with SessionLocal() as s, s.begin():
        assert await jobs.cleanup_search_terms(s) == 2
    left = {r.day for r in (await committed_db.execute(select(SearchTermDaily.day))).all()}
    assert left == {today - timedelta(days=1)}
    assert list((await committed_db.execute(select(SearchTermSearcher.searcher))).scalars()) == ["b" * 22]


async def test_settings_validation(dev_header, committed_db, client) -> None:
    admin = await make_member(committed_db, level=9, is_admin=True)
    await committed_db.commit()
    h = as_member(admin.id)
    ok = await client.patch("/api/admin/settings/search", json={"excluded_terms": ["홍길동"], "popular_min_people": 3}, headers=h)
    assert ok.status_code == 200
    for bad in ({"popular_min_people": 1}, {"popular_min_people": 51}, {"excluded_terms": [""]}, {"excluded_terms": ["가"] * 101}):
        assert (await client.patch("/api/admin/settings/search", json=bad, headers=h)).status_code == 422, bad


async def test_dashboard_shows_popular_terms_to_admin_only(dev_header, committed_db, client) -> None:
    """대시보드의 지금 인기 검색어 — 사이트 운영자만(사용자 결정, 사후 대응)"""
    from app.models import BoardModerator

    admin = await make_member(committed_db, level=9, is_admin=True)
    mod = await make_member(committed_db, level=1)
    board = await make_board(committed_db, slug="free")
    committed_db.add(BoardModerator(board_id=board.id, member_id=mod.id))
    today = _today()
    await _put_daily(committed_db, [(today, "회의", 9, 5, 1), (today - timedelta(days=1), "회의", 9, 5, 1)])
    await _rebuild()
    assert (await client.get("/api/admin/summary", headers=as_member(admin.id))).json()["popular_terms"] == [{"term": "회의", "display": "회의"}]
    assert (await client.get("/api/admin/summary", headers=as_member(mod.id))).json()["popular_terms"] is None
