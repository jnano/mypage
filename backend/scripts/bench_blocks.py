"""홈블록 API p95 — 홈블록 설계도 §12 예산을 서버 내부 시간(Server-Timing app;dur)으로 판정한다(걸음 8).

전제: 측정 DB(scripts.seed_posts → scripts.seed_blocks → VACUUM ANALYZE)로 띄운 FastAPI(SERVER_TIMING=true,
DEV_VIEWER_HEADER=true, --reload 없이). 순차 요청, 종류마다 예열 뒤 PER_KIND 회. 공개 묶음은 Next 가 캐시하므로 여기 숫자는
**캐시가 빈 때 FastAPI 한 번의 값**이다(화면 TTFB 는 k6 로 따로).

실행: cd backend && DATABASE_URL=…/mypage_hb_bench uv run python -m scripts.bench_blocks --base http://127.0.0.1:8100 --out <파일>
"""

import argparse
import asyncio
import random
import statistics
from collections import defaultdict
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
SIZE_BUDGET = 200 * 1024  # 최대 구성 틀 묶음 ≤ 200KB(§12)

# 종류 → (예산 ms 또는 None(진단값), 쿼리 예산 또는 None)
BUDGETS: dict[str, tuple[float | None, int | None]] = {
    "틀 묶음 · 게시판(최대 틀)": (30.0, 8),
    "틀 묶음 · 최대 페이지(틀 60 + 페이지 60)": (30.0, 8),
    "틀 묶음 · 게시판(보통 틀)": (30.0, 8),
    "틀 묶음 · 보통 페이지": (30.0, 8),
    "주소 집합": (None, None),
    "개인 틀 · 최대 페이지(회원)": (None, 8),
    "회원 블록 30": (30.0, 8),
    "블록 종류(관리)": (None, None),
    "끊긴 참조(관리)": (None, None),
    "대시보드 요약(관리)": (None, None),
}


async def people() -> tuple[int, list[int]]:
    async with SessionLocal() as db:
        admin = (await db.execute(select(Member.id).where(Member.is_admin.is_(True)).order_by(Member.id).limit(1))).scalar_one()
        members = list((await db.execute(select(Member.id).where(Member.level.in_([2, 3]), Member.is_admin.is_(False)).order_by(Member.id).limit(50))).scalars())
    return admin, members


async def main(base: str, out: str) -> None:
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
        plan = [k for k in kinds for _ in range(PER_KIND)]
        rnd.shuffle(plan)
        for k in kinds:  # 예열
            for _ in range(WARMUP):
                path, headers = kinds[k]()
                await client.get(path, headers=headers)
        stats: dict[str, list[tuple[float, float, int, int]]] = defaultdict(list)
        errors: dict[tuple[str, int], int] = defaultdict(int)
        for k in plan:
            path, headers = kinds[k]()
            res = await client.get(path, headers=headers)
            if res.status_code != 200:
                errors[(k, res.status_code)] += 1
                continue
            m = TIMING.fullmatch(res.headers.get("server-timing", ""))
            if not m:
                raise SystemExit("Server-Timing 이 없습니다 — SERVER_TIMING=true 로 띄우세요")
            stats[k].append((float(m.group(1)), float(m.group(2)), int(m.group(3)), len(res.content)))

    lines = [
        f"# 홈블록 API p95 — {datetime.now().isoformat(timespec='minutes')}",
        "",
        f"DB `{name}`, 서버 내부 시간(Server-Timing app;dur), 순차 요청(종류를 섞음), 종류마다 예열 {WARMUP}회 제외·{PER_KIND}회. 회원 블록 30 = /bench-member 의 개인 블록 {len(personal[:30])}개.",
        "",
        "| 종류 | n | p50 ms | p95 ms | 최대 ms | DB p95 ms | 쿼리(최대) | 응답 KB(최대) | 예산 | 판정 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for k in kinds:
        rows = stats.get(k, [])
        if not rows:
            continue
        app = [r[0] for r in rows]
        db = [r[1] for r in rows]
        q = max(r[2] for r in rows)
        size = max(r[3] for r in rows)
        budget_ms, budget_q = BUDGETS[k]
        p95 = pct(app, 95)
        ok = (budget_ms is None or p95 <= budget_ms) and (budget_q is None or q <= budget_q) and (not k.startswith("틀 묶음") or size <= SIZE_BUDGET)
        budget = " · ".join(x for x in [f"≤{budget_ms:.0f}ms" if budget_ms else "", f"쿼리 ≤{budget_q}" if budget_q else "", "≤200KB" if k.startswith("틀 묶음") else ""] if x) or "진단값"
        verdict = "진단" if budget == "진단값" else ("통과" if ok else "초과")
        lines.append(f"| {k} | {len(rows)} | {statistics.median(app):.1f} | {p95:.1f} | {max(app):.1f} | {pct(db, 95):.1f} | {q} | {size / 1024:.0f} | {budget} | {verdict} |")
    if errors:
        lines += ["", "오류 응답: " + ", ".join(f"{k[0]} {k[1]} × {v}" for k, v in sorted(errors.items()))]
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8100")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    asyncio.run(main(args.base, args.out))
