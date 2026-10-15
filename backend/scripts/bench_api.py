"""API p95 — 설계도 §15.1 예산을 서버 내부 시간(Server-Timing app;dur)으로 판정한다(1단계 측정).

전제: 측정 DB 로 띄운 FastAPI(SERVER_TIMING=true, DEV_VIEWER_HEADER=true, --reload 없이).
요청은 섞는다 — 게시판 여러 개 × 쪽(1·깊은 쪽·마지막) × 비회원/회원, 글 보기, 검색어 여러 개, 개인 조각.
예열 요청은 통계에서 뺀다. 회원 요청은 측정용 회원 여러 명에게 나눠 요청 수 한도를 피한다. 순서는 고정 난수.

실행: cd backend && DATABASE_URL=…/mypage_bench uv run python -m scripts.bench_api --base http://127.0.0.1:8000 --out <파일>
"""

import argparse
import asyncio
import random
import re
import statistics
from collections import defaultdict
from datetime import datetime
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.db.session import SessionLocal, engine
from app.models import Board, Member, Post

SEED = 7
WARMUP = 30
PER_KIND = 200
TIMING = re.compile(r'app;dur=([\d.]+), db;dur=([\d.]+);desc="q=(\d+)"(?:, pool;desc="peak=\d+/\d+")?')

BUDGET_MS = {"목록": 50.0, "글 보기": 30.0, "검색": 150.0, "개인 조각": 50.0}
SEARCH_WORDS = ["회의", "안내", "모집", "분기결산", "회의 자료", "장비대여", "노트북", "주간일정", "시설 점검"]


async def sample() -> dict:
    async with SessionLocal() as db:
        boards = {b.slug: b for b in (await db.execute(select(Board))).scalars()}
        members = list((await db.execute(
            select(Member.id).where(Member.level.in_([2, 3]), Member.is_admin.is_(False)).limit(100)
        )).scalars())  # fmt: skip
        post_ids = list((await db.execute(
            select(Post.id).where(Post.status == "published", Post.is_secret.is_(False), Post.is_blinded.is_(False),  # post-clause: exempt — 측정 표본 고르기
                                  Post.min_view_level.is_(None), Post.board_id.in_([boards["free"].id, boards["qna"].id]))
            .order_by(Post.id).limit(5000)
        )).scalars())  # fmt: skip
    return {"boards": boards, "members": members, "post_ids": post_ids}


def build_requests(s: dict, rnd: random.Random, last_pages: dict[str, int]) -> list[tuple[str, str, str | None]]:
    """(종류, 경로, 회원 id 또는 None)"""
    reqs = []
    public_boards = ["free", "qna", "consult", "notice", "small-a"]
    for _ in range(PER_KIND):
        member = str(rnd.choice(s["members"])) if rnd.random() < 0.5 else None
        board = rnd.choice(public_boards + (["members"] if member else []))
        last = last_pages.get(board, 1)
        page = rnd.choice([1, 1, max(1, last // 2), last])
        reqs.append(("목록", f"/api/boards/{board}/page?page={page}", member))
    for _ in range(PER_KIND):
        member = str(rnd.choice(s["members"])) if rnd.random() < 0.5 else None
        reqs.append(("글 보기", f"/api/posts/{rnd.choice(s['post_ids'])}/page", member))
    for _ in range(PER_KIND):
        member = str(rnd.choice(s["members"])) if rnd.random() < 0.5 else None
        q = {"q": rnd.choice(SEARCH_WORDS), "scope": rnd.choice(["all", "all", "title"])}
        reqs.append(("검색", f"/api/search?{urlencode(q)}", member))
    for _ in range(PER_KIND):
        ids = ",".join(str(rnd.choice(s["post_ids"])) for _ in range(20))
        reqs.append(("개인 조각", f"/api/me/page-state?board=free&ids={ids}", str(rnd.choice(s["members"]))))
    rnd.shuffle(reqs)
    return reqs


def pct(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(p / 100 * (len(ordered) - 1))))]


async def main(base: str, out: str) -> None:
    name = make_url(settings.database_url).database or ""
    if not name.endswith("_bench"):
        raise SystemExit(f"측정 전용 DB 에서만 실행합니다: {name}")
    rnd = random.Random(SEED)
    s = await sample()
    await engine.dispose()
    secret = settings.dev_viewer_secret

    async with httpx.AsyncClient(base_url=base, timeout=30) as client:
        last_pages = {}
        for slug in ("free", "qna", "consult", "notice", "small-a", "members"):
            headers = {"X-Dev-Member": f"{s['members'][0]}; key={secret}"} if slug == "members" else {}
            body = (await client.get(f"/api/boards/{slug}/page", headers=headers)).json()
            last_pages[slug] = body["page"]["last_page"]
        reqs = build_requests(s, rnd, last_pages)
        warm = [("예열", f"/api/boards/free/page?page={i + 1}", None) for i in range(WARMUP)]

        stats: dict[tuple[str, str], list[tuple[float, float, int]]] = defaultdict(list)
        errors = defaultdict(int)
        for kind, path, member in warm + reqs:
            headers = {"X-Dev-Member": f"{member}; key={secret}"} if member else {}
            res = await client.get(path, headers=headers)
            if kind == "예열":
                continue
            if res.status_code != 200:
                errors[(kind, res.status_code)] += 1
                continue
            m = TIMING.fullmatch(res.headers.get("server-timing", ""))
            if not m:
                raise SystemExit("Server-Timing 이 없습니다 — SERVER_TIMING=true 로 띄우세요")
            who = "회원" if member else "비회원"
            stats[(kind, who)].append((float(m.group(1)), float(m.group(2)), int(m.group(3))))

    lines = [
        f"# API p95 — {datetime.now().isoformat(timespec='minutes')}",
        "",
        f"DB `{name}`, 서버 내부 시간(Server-Timing app;dur), 순차 요청, 예열 {WARMUP}회 제외, 종류별 {PER_KIND}회(비회원·회원 섞음).",
        "",
        "| 종류 | 보는 사람 | n | p50 ms | p95 ms | 최대 ms | DB p95 ms | 쿼리 수(최대) | 예산 | 판정 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for (kind, who), rows in sorted(stats.items()):
        app = [r[0] for r in rows]
        db = [r[1] for r in rows]
        q = max(r[2] for r in rows)
        budget = BUDGET_MS[kind]
        p95 = pct(app, 95)
        verdict = "통과" if p95 <= budget and q <= 8 else "초과"
        lines.append(
            f"| {kind} | {who} | {len(rows)} | {statistics.median(app):.1f} | {p95:.1f} | {max(app):.1f} | "
            f"{pct(db, 95):.1f} | {q} | ≤{budget:.0f} | {verdict} |"
        )
    if errors:
        lines += ["", "오류 응답: " + ", ".join(f"{k[0]} {k[1]} × {v}" for k, v in sorted(errors.items()))]
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    asyncio.run(main(args.base, args.out))
