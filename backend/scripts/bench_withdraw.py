"""탈퇴 처리 시간 측정 — 검토 v4 T-1. 글 N·댓글 M 건인 회원 하나의 탈퇴를 재고 **되돌린다**(측정 DB 는 그대로).

- 요청: withdraw_member(회원 행 정리 + outbox member.withdrawn) — 사용자가 기다리는 시간
- 작업자: handlers.member_withdrawn 한 묶음(이벤트 하나 = 트랜잭션 하나)씩 끝날 때까지 — 묶음 수·묶음당 시간·합계

실행: DATABASE_URL=…/mypage_bench uv run python -m scripts.bench_withdraw [--posts 10000] [--comments 30000] [--runs 3]
측정 전용 DB(이름이 _bench 로 끝남)에서만 돈다.
"""

import argparse
import asyncio
import json
import statistics
import time
from types import SimpleNamespace

from sqlalchemy import select, text

from app.auth.account import withdraw_member
from app.auth.viewer import Viewer
from app.db.session import SessionLocal, engine
from app.models import Member, OutboxEvent
from app.worker import handlers
from scripts.seed_posts import _assert_bench_db


async def one_run(posts: int, comments: int) -> dict:
    async with SessionLocal() as db:
        await db.begin()
        try:
            member = (
                await db.execute(select(Member).where(Member.status == "active", Member.is_admin.is_(False)).order_by(Member.id.desc()).limit(1))
            ).scalar_one()
            admin_id = (await db.execute(select(Member.id).where(Member.is_admin).limit(1))).scalar_one()
            # 그 회원에게 글·댓글을 몰아 준다(측정용 — 끝나면 되돌린다)
            await db.execute(
                text("UPDATE posts SET member_id = :m WHERE id IN (SELECT id FROM posts WHERE NOT is_guest ORDER BY id LIMIT :n)"),
                {"m": member.id, "n": posts},
            )
            await db.execute(
                text("UPDATE comments SET member_id = :m WHERE id IN (SELECT id FROM comments ORDER BY id LIMIT :n)"),
                {"m": member.id, "n": comments},
            )
            owned = (await db.execute(text("SELECT (SELECT count(*) FROM posts WHERE member_id = :m), (SELECT count(*) FROM comments WHERE member_id = :m)"), {"m": member.id})).one()
            started = time.perf_counter()
            await withdraw_member(db, Viewer(member_id=admin_id, level=9, is_admin=True), member, "측정")
            request_ms = (time.perf_counter() - started) * 1000
            event = SimpleNamespace(payload={"member_id": member.id})
            batches: list[float] = []
            owned_sql = text("SELECT EXISTS (SELECT 1 FROM posts WHERE member_id = :m) OR EXISTS (SELECT 1 FROM comments WHERE member_id = :m)")
            while (await db.execute(owned_sql, {"m": member.id})).scalar_one():
                t = time.perf_counter()
                await handlers.member_withdrawn(db, event)  # 처리기는 payload 만 읽는다
                batches.append((time.perf_counter() - t) * 1000)
            payloads = (await db.execute(select(OutboxEvent.payload).where(OutboxEvent.type == "cache.revalidate"))).scalars().all()
            return {
                "posts": owned[0],
                "comments": owned[1],
                "request_ms": round(request_ms, 1),
                "worker_batches": len(batches),
                "batch_p50_ms": round(statistics.median(batches), 1),
                "batch_max_ms": round(max(batches), 1),
                "worker_total_ms": round(sum(batches), 1),
                "tags": sum(len(p["now"]) + len(p["max"]) for p in payloads),
                "largest_event_kb": round(max(len(json.dumps(p, ensure_ascii=False).encode()) for p in payloads) / 1024, 1),
            }
        finally:
            await db.rollback()


async def main(posts: int, comments: int, runs: int) -> None:
    _assert_bench_db()
    results = [await one_run(posts, comments) for _ in range(runs)]
    for r in results:
        print(r)
    print(f"요청 중앙 {statistics.median(r['request_ms'] for r in results)}ms · 작업자 합계 중앙 {statistics.median(r['worker_total_ms'] for r in results)}ms (묶음 {handlers.WITHDRAWN_BATCH}행)")
    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--posts", type=int, default=10000)
    parser.add_argument("--comments", type=int, default=30000)
    parser.add_argument("--runs", type=int, default=3)
    a = parser.parse_args()
    asyncio.run(main(a.posts, a.comments, a.runs))
