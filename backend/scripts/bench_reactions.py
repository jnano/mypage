"""글 반응의 뜨거운 행 측정 — 설계도 §6.1 '카운터 정합'·'측정'.

한 글에 동시 20 회원이 추천을 켤 때(post_stats 한 행에 잠금이 줄 선다)와, 대조군으로 같은 조건에서
서로 다른 글 20개에 켤 때의 서버 내부 시간(Server-Timing app;dur) p95 를 잰다. 차이를 뜨거운 행의 비용으로 본다(D-104).
daily 조회도 같은 방식(같은 글 20 비회원 / 서로 다른 글 20). 판정: p95 ≤ 30ms, 차이 ≤ 10ms.

전제: 측정 DB 로 띄운 FastAPI(SERVER_TIMING=true, DEV_VIEWER_HEADER=true, ENV=dev, --reload 없이).
요청 수 제한에 걸리지 않게 한 회원은 한 회차에 한 번만 누르고, 조회는 X-Client-IP 를 요청마다 다르게 싣는다.
측정 뒤 이 스크립트가 만든 반응 행·조회 기록·카운터 변화를 되돌린다.

실행: cd backend && DATABASE_URL=…/mypage_bench uv run python -m scripts.bench_reactions --base http://127.0.0.1:8100 --out <파일>
"""

import argparse
import asyncio
import re
import secrets
import statistics
from datetime import datetime

import httpx
from sqlalchemy import delete, select, update
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.db.session import SessionLocal, engine
from app.models import Board, Member, Post, PostReaction, PostStat, PostViewDaily, RateLimitCounter

ROUNDS = 10
CONCURRENCY = 20
TIMING = re.compile(r"app;dur=([\d.]+)")
BUDGET_MS, DIFF_MS = 30.0, 10.0


def p95(xs: list[float]) -> float:
    return statistics.quantiles(xs, n=20)[18] if len(xs) >= 20 else max(xs)


async def sample() -> tuple[list[int], list[int]]:
    async with SessionLocal() as db:
        free, mode = (await db.execute(select(Board.id, Board.view_count_mode).where(Board.slug == "free"))).one()
        if mode != "daily":
            raise SystemExit(f"free 게시판의 조회 방식이 daily 가 아닙니다: {mode}")
        members = list((await db.execute(
            select(Member.id).where(Member.status == "active", Member.is_admin.is_(False)).order_by(Member.id).limit(CONCURRENCY * ROUNDS)
        )).scalars())  # fmt: skip
        posts = list((await db.execute(
            select(Post.id).where(Post.board_id == free, Post.status == "published", Post.is_secret.is_(False),  # post-clause: exempt — 측정 표본 고르기
                                  Post.is_blinded.is_(False), Post.min_view_level.is_(None)).order_by(Post.id).limit(CONCURRENCY + 1)
        )).scalars())  # fmt: skip
    return members, posts


async def burst(client: httpx.AsyncClient, reqs: list[tuple[str, str, dict]]) -> list[float]:
    async def one(method: str, url: str, headers: dict) -> float:
        res = await client.request(method, url, headers=headers)
        res.raise_for_status()
        m = TIMING.search(res.headers.get("server-timing", ""))
        if m is None:
            raise SystemExit("Server-Timing 이 없습니다 — SERVER_TIMING=true 로 띄우세요")
        return float(m.group(1))

    return await asyncio.gather(*(one(*r) for r in reqs))


def member_headers(member_id: int) -> dict:
    return {"X-Dev-Member": f"{member_id}; key={settings.dev_viewer_secret}"}


async def run(base: str) -> dict[str, list[float]]:
    members, posts = await sample()
    if len(members) < CONCURRENCY * ROUNDS or len(posts) < CONCURRENCY + 1:
        raise SystemExit(f"표본 부족: 회원 {len(members)}, 글 {len(posts)}")
    hot, spread = posts[0], posts[1:]
    async with SessionLocal() as db:
        before = {r.post_id: (r.like_count, r.view_count) for r in await db.execute(select(PostStat.post_id, PostStat.like_count, PostStat.view_count).where(PostStat.post_id.in_(posts)))}
    out: dict[str, list[float]] = {"추천 — 한 글": [], "추천 — 서로 다른 글": [], "daily 조회 — 한 글": [], "daily 조회 — 서로 다른 글": []}
    headers = {"X-Internal-Secret": settings.internal_api_secret}
    async with httpx.AsyncClient(base_url=base, headers=headers, timeout=30) as client:
        await burst(client, [("GET", "/api/health/db", {})] * 5)  # 예열
        for r in range(ROUNDS):
            group = members[r * CONCURRENCY : (r + 1) * CONCURRENCY]
            ip = lambda i: {"X-Client-IP": f"198.18.{r}.{i + 1}", "X-View-Token": secrets.token_urlsafe(32)}  # noqa: E731
            # 회차마다 순서를 번갈아 — 앞 묶음의 뒷정리(연결 반납·GC)가 다음 묶음에 얹히는 치우침을 양쪽에 나눈다
            # 대조군의 회원은 다음 회차 묶음 — 같은 회원이 같은 회차에 두 번 누르지 않게(이미 켠 상태는 쓰기가 없어 가볍다)
            other = members[((r + 1) % ROUNDS) * CONCURRENCY : ((r + 1) % ROUNDS + 1) * CONCURRENCY]
            bursts = [
                ("추천 — 한 글", [("PUT", f"/api/posts/{hot}/like", member_headers(m)) for m in group]),
                ("추천 — 서로 다른 글", [("PUT", f"/api/posts/{p}/like", member_headers(m)) for m, p in zip(other, spread, strict=True)]),
                ("daily 조회 — 한 글", [("POST", f"/api/posts/{hot}/view", ip(i)) for i in range(CONCURRENCY)]),
                ("daily 조회 — 서로 다른 글", [("POST", f"/api/posts/{p}/view", ip(i + 100)) for i, p in enumerate(spread)]),
            ]
            if r % 2:
                bursts = [bursts[1], bursts[0], bursts[3], bursts[2]]
            for name, reqs in bursts:
                out[name] += await burst(client, reqs)
    await cleanup(members, posts, before)
    return out


async def cleanup(members: list[int], posts: list[int], before: dict[int, tuple[int, int]]) -> None:
    """만든 반응·조회 기록을 지우고 카운터를 되돌린다(측정 DB 를 다음 측정과 같게)"""
    async with SessionLocal() as db, db.begin():
        await db.execute(delete(PostReaction).where(PostReaction.member_id.in_(members), PostReaction.post_id.in_(posts)))
        await db.execute(delete(PostViewDaily).where(PostViewDaily.post_id.in_(posts), PostViewDaily.viewer_key.like("g:%")))
        for post_id, (likes, views) in before.items():
            await db.execute(update(PostStat).where(PostStat.post_id == post_id).values(like_count=likes, view_count=views))
        await db.execute(delete(RateLimitCounter).where(RateLimitCounter.key.like("post.%")))


def report(out: dict[str, list[float]]) -> str:
    lines = [f"# 글 반응 뜨거운 행 측정 — {datetime.now():%Y-%m-%d %H:%M}", "", f"- DB: `{make_url(settings.database_url).database}`, 동시 {CONCURRENCY} × {ROUNDS}회", ""]
    lines += ["| 경우 | 중앙 ms | p95 ms | 최대 ms |", "|---|---|---|---|"]
    for name, xs in out.items():
        lines.append(f"| {name} | {statistics.median(xs):.1f} | {p95(xs):.1f} | {max(xs):.1f} |")
    lines.append("")
    for kind in ("추천", "daily 조회"):
        hot, spread = p95(out[f"{kind} — 한 글"]), p95(out[f"{kind} — 서로 다른 글"])
        ok = hot <= BUDGET_MS and hot - spread <= DIFF_MS
        lines.append(f"- {kind}: 한 글 p95 {hot:.1f}ms, 차이 {hot - spread:+.1f}ms → {'통과' if ok else '넘음'}(p95 ≤ {BUDGET_MS:.0f}ms, 차이 ≤ {DIFF_MS:.0f}ms)")
    return "\n".join(lines) + "\n"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--out")
    args = parser.parse_args()
    if not (make_url(settings.database_url).database or "").endswith("_bench"):
        raise SystemExit("측정 전용 DB(_bench)에서만 돌린다")
    try:
        text = report(await run(args.base))
    finally:
        await engine.dispose()
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)


if __name__ == "__main__":
    asyncio.run(main())
