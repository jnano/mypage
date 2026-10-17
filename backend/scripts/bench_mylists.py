"""내 목록 측정 — 설계도 §6.2 '성능': 많이 쓴 회원의 내 글·내 댓글·스크랩 첫 쪽·깊은 쪽 p95 ≤ 50ms(서버 내부, 순차).

측정 DB 에는 글을 1만 건 쓴 회원·스크랩 1만 건이 없으므로, 측정하는 동안만 한 회원(댓글이 가장 많은 회원)에게
다른 회원의 글 1만 건을 옮기고 스크랩 1만 건을 만든다. 끝나면(실패해도) 원래대로 되돌린다.
깊은 쪽 = 앞에서 9,000번째 행 뒤의 커서. 커서 행 비교가 인덱스 조건인지 Filter 인지 EXPLAIN 으로 함께 남긴다(검토 묶음B N-1).

전제: 측정 DB 로 띄운 FastAPI(SERVER_TIMING=true, DEV_VIEWER_HEADER=true, ENV=dev, --reload 없이).
실행: cd backend && DATABASE_URL=…/mypage_bench uv run python -m scripts.bench_mylists --base http://127.0.0.1:8100 --out <파일>
"""

import argparse
import asyncio
import re
import statistics
from datetime import datetime
from urllib.parse import quote

import httpx
from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.db.session import SessionLocal, engine

N = 10_000
DEEP = 9_000
REPS = 50
BUDGET_MS = 50.0
TIMING = re.compile(r"app;dur=([\d.]+), db;dur=([\d.]+);desc=\"q=(\d+)\"")

# 앱 문장과 같은 꼴(app/me/lists.py) — EXPLAIN 용
DEEP_SQL = {
    "내 글": "SELECT posts.id FROM posts WHERE posts.member_id = :m AND posts.status <> 'trashed' AND (posts.created_at, posts.id) < (:at, :id) ORDER BY posts.created_at DESC, posts.id DESC LIMIT 31",
    "내 댓글": "SELECT comments.id FROM comments WHERE comments.member_id = :m AND comments.status = 'published' AND (comments.created_at, comments.id) < (:at, :id) ORDER BY comments.created_at DESC, comments.id DESC LIMIT 31",
    "스크랩": "SELECT post_scraps.post_id FROM post_scraps WHERE post_scraps.member_id = :m AND (post_scraps.created_at, post_scraps.post_id) < (:at, :id) ORDER BY post_scraps.created_at DESC, post_scraps.post_id DESC LIMIT 31",
}
ORDER_SQL = {
    "내 글": "SELECT created_at, id FROM posts WHERE member_id = :m AND status <> 'trashed' ORDER BY created_at DESC, id DESC OFFSET :k LIMIT 1",
    "내 댓글": "SELECT created_at, id FROM comments WHERE member_id = :m AND status = 'published' ORDER BY created_at DESC, id DESC OFFSET :k LIMIT 1",
    "스크랩": "SELECT created_at, post_id AS id FROM post_scraps WHERE member_id = :m ORDER BY created_at DESC, post_id DESC OFFSET :k LIMIT 1",
}
PATHS = {"내 글": "/api/me/posts", "내 댓글": "/api/me/comments", "스크랩": "/api/me/scraps"}


def p95(xs: list[float]) -> float:
    return statistics.quantiles(xs, n=20)[18]


async def prepare() -> int:
    """댓글이 가장 많은 회원에게 글 1만 건을 옮기고 스크랩 1만 건을 만든다 — 옮긴 글은 임시 표에 적어 되돌린다"""
    async with SessionLocal() as db, db.begin():
        m = (await db.execute(text("SELECT member_id FROM comments WHERE member_id IS NOT NULL GROUP BY 1 ORDER BY count(*) DESC LIMIT 1"))).scalar_one()
        await db.execute(text("CREATE TABLE IF NOT EXISTS bench_mylists_moved (post_id bigint PRIMARY KEY, member_id bigint)"))
        await db.execute(
            text(
                "INSERT INTO bench_mylists_moved SELECT id, member_id FROM posts WHERE member_id IS DISTINCT FROM :m AND member_id IS NOT NULL ORDER BY id LIMIT :n"
            ),
            {"m": m, "n": N},
        )
        await db.execute(text("UPDATE posts SET member_id = :m, updated_at = posts.updated_at FROM bench_mylists_moved b WHERE posts.id = b.post_id"), {"m": m})
        await db.execute(
            text(
                "INSERT INTO post_scraps (post_id, member_id, created_at) SELECT id, :m, now() - (row_number() OVER (ORDER BY id)) * interval '1 minute' FROM posts WHERE status = 'published' ORDER BY id LIMIT :n ON CONFLICT DO NOTHING"
            ),
            {"m": m, "n": N},
        )
    async with engine.connect() as conn:
        conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        await conn.execute(text("ANALYZE posts, comments, post_scraps"))
    return m


async def restore(m: int) -> None:
    async with SessionLocal() as db, db.begin():
        await db.execute(text("UPDATE posts SET member_id = b.member_id, updated_at = posts.updated_at FROM bench_mylists_moved b WHERE posts.id = b.post_id"))
        await db.execute(text("DROP TABLE IF EXISTS bench_mylists_moved"))
        await db.execute(text("DELETE FROM post_scraps WHERE member_id = :m"), {"m": m})


async def cursor_at(m: int, kind: str) -> tuple[datetime, int]:
    async with SessionLocal() as db:
        row = (await db.execute(text(ORDER_SQL[kind]), {"m": m, "k": DEEP - 1})).one()
    return row.created_at, row.id


async def explain(m: int, kind: str, at: datetime, rid: int) -> str:
    async with SessionLocal() as db:
        rows = (await db.execute(text("EXPLAIN (ANALYZE, BUFFERS) " + DEEP_SQL[kind]), {"m": m, "at": at, "id": rid})).scalars()
        return "\n".join(rows)


async def run(base: str) -> str:
    m = await prepare()
    try:
        lines = [f"# 내 목록 측정 — {datetime.now():%Y-%m-%d %H:%M}", "", f"- DB `{make_url(settings.database_url).database}`, 회원 {m}(글 {N:,}건을 잠시 옮기고 스크랩 {N:,}건), 순차 {REPS}회, 깊은 쪽 = {DEEP:,}번째 행 뒤", ""]
        lines += ["| 목록 | 첫 쪽 p95 ms | 깊은 쪽 p95 ms | 쿼리 수 |", "|---|---|---|---|"]
        plans = []
        headers = {"X-Internal-Secret": settings.internal_api_secret, "X-Dev-Member": f"{m}; key={settings.dev_viewer_secret}"}
        async with httpx.AsyncClient(base_url=base, headers=headers, timeout=30) as client:
            for kind, path in PATHS.items():
                at, rid = await cursor_at(m, kind)
                deep = f"{path}?cursor={quote(f'{at.isoformat()}|{rid}')}"
                result = {}
                for name, url in (("first", path), ("deep", deep)):
                    for _ in range(5):
                        (await client.get(url)).raise_for_status()  # 예열
                    times, qs = [], set()
                    for _ in range(REPS):
                        res = await client.get(url)
                        res.raise_for_status()
                        a, _, q = TIMING.search(res.headers["server-timing"]).groups()
                        times.append(float(a))
                        qs.add(int(q))
                    result[name] = (p95(times), qs)
                lines.append(f"| {kind} | {result['first'][0]:.1f} | {result['deep'][0]:.1f} | {sorted(result['first'][1] | result['deep'][1])} |")
                plans.append(f"### {kind} — 깊은 쪽\n\n```\n{await explain(m, kind, at, rid)}\n```")
        worst = max(float(x.split("|")[3]) for x in lines if x.startswith("| 내") or x.startswith("| 스크랩"))
        lines += ["", f"- 판정: 깊은 쪽 최댓값 p95 {worst:.1f}ms → {'통과' if worst <= BUDGET_MS else '넘음'}(≤ {BUDGET_MS:.0f}ms)", "", *plans]
        return "\n".join(lines) + "\n"
    finally:
        await restore(m)


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
