"""홈블록 API p95 — 홈블록 설계도 §12 예산을 서버 내부 시간(Server-Timing app;dur)으로 판정한다(걸음 8).

전제: 측정 DB(scripts.seed_posts → scripts.seed_blocks → VACUUM ANALYZE)로 띄운 FastAPI(SERVER_TIMING=true,
DEV_VIEWER_HEADER=true, --reload 없이). 순차 요청, 종류마다 예열 뒤 PER_KIND 회를 --rounds 번(기본 3) 잰다. 판정은
**각 판 p95 의 중앙값**(§12 경계 판정 — 같은 기계의 다른 작업으로 p95 가 ±2ms 흔들린다). 공개 묶음은 Next 가 캐시하므로
여기 숫자는 **캐시가 빈 때 FastAPI 한 번의 값**이다(화면 TTFB 는 k6 로 따로).

예산(§12 — 걸음 8 결정 ③④): 보통 구성은 판정(≤ 30ms), 최대 구성은 진단 상한(틀 ≤ 100ms·틀 + 페이지 ≤ 300ms·
회원 블록 30 ≤ 100ms — M-11), 묶음 하나당 쿼리 ≤ 8, 응답 크기 틀 묶음 ≤ 200KB·주소 묶음(틀 + 페이지) ≤ 400KB.

실행: cd backend && DATABASE_URL=…/mypage_hb_bench uv run python -m scripts.bench_blocks --base http://127.0.0.1:8100 --out <파일>
"""

import argparse
import asyncio
import random
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.db.session import SessionLocal, engine
from app.models import Member
from scripts.bench_api import TIMING, pct

SEED = 8
WARMUP = 10
PER_KIND = 200
ROUNDS = 3
FRAME_KB = 200  # 틀 묶음(주인 하나) ≤ 200KB(§12)
PATH_KB = 400  # 주소 묶음(틀 + 페이지, 주인 둘) ≤ 400KB(§12)


@dataclass(frozen=True)
class Budget:
    """§12 예산 한 줄. ms 가 None 이면 시간은 진단값(상한 없음). diagnostic 이면 최대 구성의 진단 상한(넘으면 '초과'로 적되
    예산 판정이 아니다) — 판정 칸에 '진단 통과/초과'로 갈라 적는다"""

    ms: float | None = None
    queries: int | None = None
    kb: int | None = None
    diagnostic: bool = False


BUDGETS: dict[str, Budget] = {
    "틀 묶음 · 게시판(최대 틀)": Budget(100.0, 8, FRAME_KB, diagnostic=True),
    "틀 묶음 · 최대 페이지(틀 60 + 페이지 60)": Budget(300.0, 8, PATH_KB, diagnostic=True),
    "틀 묶음 · 게시판(보통 틀)": Budget(30.0, 8, FRAME_KB),
    "틀 묶음 · 보통 페이지": Budget(30.0, 8, PATH_KB),
    "주소 집합": Budget(),
    "개인 틀 · 최대 페이지(회원)": Budget(300.0, 8, PATH_KB, diagnostic=True),
    "회원 블록 30": Budget(100.0, 8, diagnostic=True),  # M-11 — 최대 구성(30개) 진단 상한
    "블록 종류(관리)": Budget(),
    "끊긴 참조(관리)": Budget(),
    "대시보드 요약(관리)": Budget(),
}


def verdict(b: Budget, p95: float, queries: int, size: int) -> tuple[str, str]:
    """(예산 글, 판정) — 판정은 통과/초과(보통 구성), 진단 통과/진단 초과(최대 구성), 진단(상한 없음)"""
    parts = [f"≤{b.ms:.0f}ms" if b.ms else "", f"쿼리 ≤{b.queries}" if b.queries else "", f"≤{b.kb}KB" if b.kb else ""]
    text = " · ".join(x for x in parts if x) or "진단값"
    if text == "진단값":
        return text, "진단"
    ok = (b.ms is None or p95 <= b.ms) and (b.queries is None or queries <= b.queries) and (b.kb is None or size <= b.kb * 1024)
    return (f"{text}(진단 상한)" if b.diagnostic else text), ("진단 " if b.diagnostic else "") + ("통과" if ok else "초과")


async def people() -> tuple[int, list[int]]:
    async with SessionLocal() as db:
        admin = (await db.execute(select(Member.id).where(Member.is_admin.is_(True)).order_by(Member.id).limit(1))).scalar_one()
        members = list((await db.execute(select(Member.id).where(Member.level.in_([2, 3]), Member.is_admin.is_(False)).order_by(Member.id).limit(50))).scalars())
    return admin, members


async def main(base: str, out: str, rounds: int) -> None:
    name = make_url(settings.database_url).database or ""
    if not name.endswith("_bench"):
        raise SystemExit(f"측정 전용 DB 에서만 실행합니다: {name}")
    rnd = random.Random(SEED)
    admin, members = await people()
    await engine.dispose()
    secret = settings.dev_viewer_secret
    as_ = lambda who: {"X-Dev-Member": f"{who}; key={secret}"}  # noqa: E731

    async with httpx.AsyncClient(base_url=base, timeout=60) as client:
        personal = (await client.get("/api/frame", params={"path": "/bench-member"})).json()["personal_block_ids"]
        blocks_q = ",".join(map(str, personal[:30]))
        kinds = {
            "틀 묶음 · 게시판(최대 틀)": lambda: ("/api/frame?board=free", {}),
            "틀 묶음 · 최대 페이지(틀 60 + 페이지 60)": lambda: ("/api/frame?path=%2Fbench-max", {}),
            "틀 묶음 · 게시판(보통 틀)": lambda: ("/api/frame?board=qna", {}),
            "틀 묶음 · 보통 페이지": lambda: ("/api/frame?path=%2Fbench-typical", {}),
            "주소 집합": lambda: ("/api/pages/paths", {}),
            "개인 틀 · 최대 페이지(회원)": lambda: ("/api/me/frame?path=%2Fbench-max", as_(rnd.choice(members))),
            "회원 블록 30": lambda: (f"/api/me/page-state?blocks={blocks_q}", as_(rnd.choice(members))),
            "블록 종류(관리)": lambda: ("/api/admin/block-types", as_(admin)),
            "끊긴 참조(관리)": lambda: ("/api/admin/blocks/dangling", as_(admin)),
            "대시보드 요약(관리)": lambda: ("/api/admin/summary", as_(admin)),
        }
        for k in kinds:  # 예열
            for _ in range(WARMUP):
                path, headers = kinds[k]()
                await client.get(path, headers=headers)
        # 판마다 종류 → [(app ms, db ms, 쿼리, 바이트)]
        stats: list[dict[str, list[tuple[float, float, int, int]]]] = [defaultdict(list) for _ in range(rounds)]
        errors: dict[tuple[str, int], int] = defaultdict(int)
        for round_stats in stats:
            plan = [k for k in kinds for _ in range(PER_KIND)]
            rnd.shuffle(plan)
            for k in plan:
                path, headers = kinds[k]()
                res = await client.get(path, headers=headers)
                if res.status_code != 200:
                    errors[(k, res.status_code)] += 1
                    continue
                m = TIMING.fullmatch(res.headers.get("server-timing", ""))
                if not m:
                    raise SystemExit("Server-Timing 이 없습니다 — SERVER_TIMING=true 로 띄우세요")
                round_stats[k].append((float(m.group(1)), float(m.group(2)), int(m.group(3)), len(res.content)))

    lines = [
        f"# 홈블록 API p95 — {datetime.now().isoformat(timespec='minutes')}",
        "",
        f"DB `{name}`, 서버 내부 시간(Server-Timing app;dur), 순차 요청(종류를 섞음), 종류마다 예열 {WARMUP}회 제외·판마다 {PER_KIND}회 × {rounds}판."
        f" 판정 = 판마다 잰 p95 의 중앙값(§12). 회원 블록 30 = /bench-member 의 개인 블록 {len(personal[:30])}개.",
        "",
        "| 종류 | n | p50 ms | p95 ms(중앙값) | 판마다 p95 범위 | 최대 ms | DB p95 ms | 쿼리(최대) | 응답 KB(최대) | 예산 | 판정 |",
        "|---|---:|---:|---:|---|---:|---:|---:|---:|---|---|",
    ]
    for k in kinds:
        per_round = [s[k] for s in stats if s.get(k)]
        if not per_round:
            continue
        rows = [r for rs in per_round for r in rs]
        app = [r[0] for r in rows]
        db = [r[1] for r in rows]
        q = max(r[2] for r in rows)
        size = max(r[3] for r in rows)
        round_p95 = [pct([r[0] for r in rs], 95) for rs in per_round]
        p95 = statistics.median(round_p95)
        budget, judged = verdict(BUDGETS[k], p95, q, size)
        spread = f"{min(round_p95):.1f} ~ {max(round_p95):.1f}"
        lines.append(f"| {k} | {len(rows)} | {statistics.median(app):.1f} | {p95:.1f} | {spread} | {max(app):.1f} | {pct(db, 95):.1f} | {q} | {size / 1024:.0f} | {budget} | {judged} |")
    if errors:
        lines += ["", "오류 응답: " + ", ".join(f"{k[0]} {k[1]} × {v}" for k, v in sorted(errors.items()))]
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8100")
    parser.add_argument("--out", required=True)
    parser.add_argument("--rounds", type=int, default=ROUNDS, help="판 수 — 판정은 판마다 잰 p95 의 중앙값(§12)")
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error("--rounds 는 1 이상")
    asyncio.run(main(args.base, args.out, args.rounds))
