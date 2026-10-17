"""인기 검색어 측정 — 설계도 §9.1 '쿼리 예산': 7일 × 검색어 1만 개 × 하루 행에서 GET /api/search/terms p95 ≤ 30ms(서버 내부, 순차),
그리고 작업자 search_terms.popular(후보 다시 만들기) 한 번의 시간.

측정하는 동안만 search_term_daily 에 'bench' 로 시작하는 검색어 7만 행을 넣고, 끝나면(실패해도) 지운다.
전제: 측정 DB 로 띄운 FastAPI(SERVER_TIMING=true, --reload 없이).
실행: cd backend && DATABASE_URL=…/mypage_bench uv run python -m scripts.bench_search_terms --base http://127.0.0.1:8100 --out <파일>
"""

import argparse
import asyncio
import random
import re
import statistics
import time
from datetime import datetime

import httpx
from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.db.session import SessionLocal, engine
from app.search.terms import POPULAR_DAYS, rebuild_popular

TERMS = 10_000
REPS = 50
BUDGET_MS = 30.0
TIMING = re.compile(r"app;dur=([\d.]+), db;dur=([\d.]+);desc=\"q=(\d+)\"")
PREFIX = "bench"


async def prepare() -> None:
    rnd = random.Random(7)
    rows = []
    for d in range(POPULAR_DAYS):
        for i in range(TERMS):
            people = rnd.choice([1, 1, 1, 2, 3, 5, 8])  # 대부분 문턱 아래
            rows.append({"d": d, "t": f"{PREFIX}{i:05d}", "s": rnd.randint(1, 200), "p": people, "m": 1 if people >= 3 else 0})
    async with SessionLocal() as db, db.begin():
        await db.execute(
            text(
                "INSERT INTO search_term_daily (day, term, display, searches, people, members) "
                "SELECT date(timezone(:tz, now())) - CAST(:d AS integer), :t, :t, :s, :p, :m"
            ),
            [r | {"tz": settings.site_time_zone} for r in rows],
        )
    async with engine.connect() as conn:
        conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        await conn.execute(text("ANALYZE search_term_daily"))


async def restore() -> None:
    async with SessionLocal() as db, db.begin():
        await db.execute(text("DELETE FROM search_term_daily WHERE term LIKE :p"), {"p": f"{PREFIX}%"})
        await rebuild_popular(db)  # 후보도 측정 전으로


async def run(base: str) -> str:
    await prepare()
    try:
        job_ms = []
        for _ in range(5):
            t0 = time.perf_counter()
            async with SessionLocal() as db, db.begin():
                await rebuild_popular(db)
            job_ms.append((time.perf_counter() - t0) * 1000)
        async with httpx.AsyncClient(base_url=base, timeout=30) as client:
            for _ in range(5):
                (await client.get("/api/search/terms")).raise_for_status()
            times, qs, n = [], set(), 0
            for _ in range(REPS):
                res = await client.get("/api/search/terms")
                res.raise_for_status()
                a, _, q = TIMING.search(res.headers["server-timing"]).groups()
                times.append(float(a))
                qs.add(int(q))
                n = len(res.json()["popular"])
        async with SessionLocal() as db:
            plan = "\n".join(
                (
                    await db.execute(
                        text(
                            "EXPLAIN (ANALYZE, BUFFERS) SELECT term FROM search_term_daily WHERE day >= date(timezone(:tz, now())) - 6 "
                            "GROUP BY term HAVING count(*) FILTER (WHERE people >= 5 AND members >= 1) >= 2 ORDER BY sum(searches) DESC, term LIMIT 50"
                        ),
                        {"tz": settings.site_time_zone},
                    )
                ).scalars()
            )
        p95 = statistics.quantiles(times, n=20)[18]
        return (
            f"# 인기 검색어 측정 — {datetime.now():%Y-%m-%d %H:%M}\n\n"
            f"- DB `{make_url(settings.database_url).database}`, {POPULAR_DAYS}일 × 검색어 {TERMS:,}개(측정하는 동안만), 순차 {REPS}회\n"
            f"- GET /api/search/terms: 중앙 {statistics.median(times):.1f}ms · p95 {p95:.1f}ms · 쿼리 {sorted(qs)} · 인기 {n}개 → "
            f"{'통과' if p95 <= BUDGET_MS else '넘음'}(≤ {BUDGET_MS:.0f}ms)\n"
            f"- 작업자 search_terms.popular 한 번(후보 다시 만들기, 5회): 중앙 {statistics.median(job_ms):.1f}ms · 최대 {max(job_ms):.1f}ms(매시)\n\n"
            f"후보 쿼리 계획:\n\n```\n{plan}\n```\n"
        )
    finally:
        await restore()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--out")
    args = parser.parse_args()
    if not (make_url(settings.database_url).database or "").endswith("_bench"):
        raise SystemExit("측정 전용 DB(_bench)에서만 돌린다")
    try:
        report = await run(args.base)
    finally:
        await engine.dispose()
    print(report)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report)


if __name__ == "__main__":
    asyncio.run(main())
