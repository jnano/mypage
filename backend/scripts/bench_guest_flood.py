"""비회원 폭주 중 회원 로그인 — 설계도 §6.3 'argon2 한도'의 끝 조건.

비회원 비밀번호 시도(guest-token, argon2)를 동시 20 으로 계속 두드리는 동안 회원 로그인 30회(순차)의 시간을 잰다.
세 경우: (가) 몰림 없음 (나) 몰림 — 비회원은 전용 한도 argon2_guest(지금 구현) (다) 대조군 — 비회원도 로그인과 같은 한도 argon2.
같은 프로세스에서 앱을 부른다(ASGI) — 스레드 한도·이벤트 루프를 한 서버 프로세스와 같게 공유한다. 요청 수 제한은 측정 동안만 넓힌다.
측정 동안만 비회원 글 하나를 만들고, 끝나면 그 글과 측정이 만든 세션을 지운다.

실행: cd backend && DATABASE_URL=…/mypage_bench ENV=test uv run python -m scripts.bench_guest_flood --out <파일>
"""

import argparse
import asyncio
import os
import statistics
import time
from datetime import datetime

os.environ.setdefault("INTERNAL_API_SECRET", "bench-internal-secret-0123456789abcdef")

import httpx  # noqa: E402
from sqlalchemy import delete, insert, select  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from app.auth.passwords import hash_password  # noqa: E402
from app.core import rate_limit  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.rate_limit import Limit  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Board, LoginSession, Member, Post, PostStat  # noqa: E402
from app.posts import guest  # noqa: E402
from scripts.dev_auth import DEV_PASSWORD  # noqa: E402

LOGINS = 30
FLOOD = 20


def p95(xs: list[float]) -> float:
    return statistics.quantiles(xs, n=20)[18]


async def prepare() -> tuple[int, list[str], datetime]:
    started = datetime.now().astimezone()
    async with SessionLocal() as db, db.begin():
        board_id = (await db.execute(select(Board.id).where(Board.slug == "free"))).scalar_one()
        post_id = (
            await db.execute(
                insert(Post)
                .values(
                    board_id=board_id, is_guest=True, author_name_snapshot="측정손님", guest_password_hash=hash_password("flood-pass-01"),
                    title="측정용 비회원 글", content_format="rich", content_html="<p>측정</p>", content_rendered="<p>측정</p>",
                    sanitizer_version=1, status="published", published_at=started,
                )  # fmt: skip
                .returning(Post.id)
            )
        ).scalar_one()
        await db.execute(insert(PostStat).values(post_id=post_id))
        emails = list(
            (await db.execute(select(Member.email).where(Member.status == "active", Member.is_admin.is_(False), Member.email.is_not(None)).order_by(Member.id).limit(LOGINS))).scalars()
        )
    return post_id, emails, started


async def cleanup(post_id: int, started: datetime) -> None:
    async with SessionLocal() as db, db.begin():
        await db.execute(delete(Post).where(Post.id == post_id))
        await db.execute(delete(LoginSession).where(LoginSession.created_at >= started))


async def logins(client: httpx.AsyncClient, emails: list[str], tag: int) -> list[float]:
    out = []
    for i, email in enumerate(emails):
        t0 = time.perf_counter()
        res = await client.post("/api/auth/login", json={"email": email, "password": DEV_PASSWORD, "persistent": False}, headers={"X-Client-IP": f"198.18.{tag}.{i + 1}"})
        out.append((time.perf_counter() - t0) * 1000)
        if res.status_code != 200:
            raise SystemExit(f"로그인 실패 {res.status_code}: {res.text[:200]}")
    return out


async def flood(client: httpx.AsyncClient, post_id: int, stop: asyncio.Event, n: int, counter: list[int]) -> None:
    while not stop.is_set():
        await client.post(f"/api/posts/{post_id}/guest-token", json={"password": "wrong-password", "purpose": "read"}, headers={"X-Client-IP": f"198.19.{n}.1"})
        counter[0] += 1


async def scenario(client: httpx.AsyncClient, post_id: int, emails: list[str], tag: int, with_flood: bool) -> tuple[list[float], int]:
    stop, counter = asyncio.Event(), [0]
    tasks = [asyncio.create_task(flood(client, post_id, stop, n, counter)) for n in range(FLOOD)] if with_flood else []
    if tasks:
        await asyncio.sleep(1.0)  # 몰림이 자리 잡게
    try:
        times = await logins(client, emails, tag)
    finally:
        stop.set()
        await asyncio.gather(*tasks)
    return times, counter[0]


async def run() -> str:
    big = Limit(1_000_000, 60)
    for key in ("auth.login", "auth.login_account", "auth.login_ip", "auth.login_device", "guest.token", "guest.token_post"):
        rate_limit.LIMITS[key] = big
    post_id, emails, started = await prepare()
    rows = []
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://bench", headers={"X-Internal-Secret": settings.internal_api_secret}, timeout=60) as client:
            await logins(client, emails[:3], 9)  # 예열
            a, _ = await scenario(client, post_id, emails, 1, False)
            b, nb = await scenario(client, post_id, emails, 2, True)
            original = guest.run_in_thread_within
            guest.run_in_thread_within = lambda _kind, wait, fn, *args: original("argon2", wait, fn, *args)  # 대조군: 같은 한도
            try:
                c, nc = await scenario(client, post_id, emails, 3, True)
            finally:
                guest.run_in_thread_within = original
        for name, xs, n in (("(가) 몰림 없음", a, 0), ("(나) 몰림 — 비회원 전용 한도(지금)", b, nb), ("(다) 대조군 — 같은 한도", c, nc)):
            rows.append(f"| {name} | {statistics.median(xs):.0f} | {p95(xs):.0f} | {max(xs):.0f} | {n} |")
    finally:
        await cleanup(post_id, started)
    return (
        f"# 비회원 폭주 중 회원 로그인 — {datetime.now():%Y-%m-%d %H:%M}\n\n"
        f"- DB `{make_url(settings.database_url).database}`, 같은 프로세스(ASGI), 로그인 {LOGINS}회 순차, 비회원 비밀번호 시도 동시 {FLOOD}\n\n"
        "| 경우 | 로그인 중앙 ms | p95 ms | 최대 ms | 그동안 비회원 시도 수 |\n|---|---|---|---|---|\n" + "\n".join(rows) + "\n"
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out")
    args = parser.parse_args()
    if not (make_url(settings.database_url).database or "").endswith("_bench"):
        raise SystemExit("측정 전용 DB(_bench)에서만 돌린다")
    try:
        report = await run()
    finally:
        await engine.dispose()
    print(report)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report)


if __name__ == "__main__":
    asyncio.run(main())
