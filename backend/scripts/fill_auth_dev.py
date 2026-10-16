"""개발·측정 DB 의 기존 회원에 인증 칸 채우기 — 인증 설계도 §3.1 '기존 행 전환'.

순서(backend/README.md '개발'): alembic upgrade 66efce5894cc → 이 스크립트 → alembic upgrade head
실행: uv run python -m scripts.fill_auth_dev --database <연결된 DB 이름>

- ENV 가 dev·test 일 때만 돈다(prod 는 무조건 거부). DB 이름으로 개발·운영을 가르지 않는다.
- --database 는 실수 방지용 확인 값이다. 실제로 연결된 DB 이름과 다르면 거부한다.
- 채우는 값: 이메일 m{id}@example.test · 개발용 비밀번호 해시 · 표시 이름 키(겹치면 이름 뒤에 #id) ·
  14세 확인 · 개발용 고지 판(dev-notice) 동의. 이미 값이 있는 칸은 그대로 둔다.
"""

import argparse
import asyncio
from datetime import UTC, datetime

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.names import display_name_key
from app.auth.passwords import hash_password
from app.core.config import settings
from app.db.session import SessionLocal, engine
from app.models import Member
from scripts.dev_auth import DEV_PASSWORD, ensure_dev_notice


def check_target(env: str, wanted: str, connected: str) -> None:
    """돌아도 되는지 — 아니면 SystemExit"""
    if env not in ("dev", "test"):
        raise SystemExit(f"ENV={env} — 채움 스크립트는 ENV=dev·test 에서만 돈다. 운영 DB 에 자리 값을 넣지 않는다")
    if wanted != connected:
        raise SystemExit(f"--database {wanted} 와 연결된 DB({connected})가 다르다 — DATABASE_URL 을 확인한다")


async def fill(db: AsyncSession) -> int:
    """채운 회원 수. 탈퇴 회원은 건드리지 않는다"""
    notice = await ensure_dev_notice(db)
    now = datetime.now(UTC)
    rows = (
        await db.execute(
            select(Member.id, Member.display_name, Member.status, Member.display_name_key).where(
                Member.status != "withdrawn"
            )
        )
    ).all()
    # 표시 이름 키는 활동 회원끼리 고유 — 이미 있는 키를 먼저 잡고, 겹치는 이름은 '#id' 를 붙인다
    taken = {r.display_name_key for r in rows if r.display_name_key and r.status == "active"}
    password_hash = hash_password(DEV_PASSWORD)
    changes = []
    for r in sorted(rows, key=lambda r: r.id):
        name, key = r.display_name, r.display_name_key
        if key is None:
            key = display_name_key(name)
            if r.status == "active" and key in taken:
                name = f"{name}#{r.id}"
                key = display_name_key(name)
            if r.status == "active":
                taken.add(key)
        changes.append({"id": r.id, "display_name": name, "display_name_key": key})
    if changes:
        await db.execute(update(Member), changes)  # 기본키로 묶음 UPDATE
    filled = await db.execute(
        update(Member)
        .where(Member.status != "withdrawn")
        .where(
            (Member.email.is_(None))
            | Member.password_hash.is_(None)
            | Member.privacy_version.is_(None)
            | Member.privacy_agreed_at.is_(None)
            | Member.age14_confirmed_at.is_(None)
        )
        .values(
            email=func.coalesce(Member.email, func.concat("m", Member.id, "@example.test")),
            password_hash=func.coalesce(Member.password_hash, password_hash),
            privacy_version=func.coalesce(Member.privacy_version, notice),
            privacy_agreed_at=func.coalesce(Member.privacy_agreed_at, now),
            age14_confirmed_at=func.coalesce(Member.age14_confirmed_at, now),
        )
    )
    return filled.rowcount


async def main(database: str) -> None:
    async with SessionLocal() as db, db.begin():
        connected = (await db.execute(text("SELECT current_database()"))).scalar_one()
        check_target(settings.env, database, connected)
        n = await fill(db)
    await engine.dispose()
    print(f"{connected}: 회원 {n}명 채움 — 개발용 비밀번호는 backend/README.md '개발'. 다음: alembic upgrade head")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", required=True, help="연결된 DB 이름(확인용)")
    asyncio.run(main(parser.parse_args().database))
