"""마이그레이션 — 모델과 실제 DB 가 같은지(§4.8 의 DB 쪽). downgrade/upgrade 는 conftest 가 매번 돈다."""

import asyncio

import asyncpg
import pytest
from alembic import command
from sqlalchemy import CheckConstraint, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.db.base import Base
from scripts.fill_auth_dev import fill
from tests.conftest import TEST_DATABASE_URL, alembic_config
from tests.schema_spec import SPEC

AUTH_TABLES_REV = "66efce5894cc"  # 인증 ① 칸·표 추가(CHECK 전)

pytestmark = pytest.mark.anyio


def test_models_match_migrations(migrated_db: None) -> None:
    # 공식 `alembic check`: 마이그레이션 뒤 DB 와 모델 메타데이터의 차이(칸·형·NULL·기본값·FK·인덱스)가 없어야 한다
    command.check(alembic_config())


async def test_unlogged_tables(db: AsyncSession) -> None:
    rows = await db.execute(
        text(
            "SELECT relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
            " WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relpersistence = 'u'"
        )
    )
    assert set(rows.scalars()) == {name for name, t in SPEC.items() if t.unlogged}


async def test_check_constraints_exist_in_db(db: AsyncSession) -> None:
    # alembic check 는 CHECK 를 비교하지 않으므로 이름 목록을 DB 에서 직접 확인한다
    rows = await db.execute(
        text(
            "SELECT conrelid::regclass::text, conname FROM pg_constraint"
            " WHERE contype = 'c' AND connamespace = 'public'::regnamespace"
        )
    )
    in_db = {(t, n) for t, n in rows.all()}
    in_models = {
        (t.name, str(c.name))
        for t in Base.metadata.tables.values()
        for c in t.constraints
        if isinstance(c, CheckConstraint)
    }
    assert in_db == in_models


async def test_list_index_includes_expires_at(db: AsyncSession) -> None:
    # alembic check 는 INCLUDE 를 비교하지 않으므로 실제 DB 의 정의를 본다(1단계 측정으로 정한 인덱스)
    indexdef = (
        await db.execute(text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_posts_board_list'"))
    ).scalar_one()
    assert "INCLUDE (expires_at)" in indexdef
    assert "WHERE (((status)::text = 'published'::text) AND (is_pinned = false))" in indexdef


# ── 인증 칸 전환(인증 설계도 §3.1 '기존 행 전환') — 공용 시험 DB 의 스키마를 바꾸지 않도록 임시 DB 에서 돈다 ──


async def _admin(sql: str) -> None:
    url = make_url(TEST_DATABASE_URL).set(drivername="postgresql", database="postgres")
    conn = await asyncpg.connect(url.render_as_string(hide_password=False))
    try:
        await conn.execute(sql)
    finally:
        await conn.close()


async def _execute(url: str, *statements: str) -> list[tuple]:
    """문장들을 한 트랜잭션에서 차례로 — 마지막 문장의 결과 행"""
    eng = create_async_engine(url, poolclass=NullPool)
    try:
        async with AsyncSession(eng) as db, db.begin():
            result = None
            for sql in statements:
                result = await db.execute(text(sql))
            return [tuple(r) for r in result] if result is not None and result.returns_rows else []
    finally:
        await eng.dispose()


async def _fill(url: str) -> int:
    eng = create_async_engine(url, poolclass=NullPool)
    try:
        async with AsyncSession(eng) as db, db.begin():
            return await fill(db)
    finally:
        await eng.dispose()


@pytest.fixture
def scratch_db(monkeypatch: pytest.MonkeyPatch):
    name = f"{make_url(TEST_DATABASE_URL).database}_migr"
    asyncio.run(_admin(f'DROP DATABASE IF EXISTS "{name}"'))
    asyncio.run(_admin(f'CREATE DATABASE "{name}"'))
    url = make_url(TEST_DATABASE_URL).set(database=name).render_as_string(hide_password=False)
    monkeypatch.setattr(settings, "database_url", url)  # alembic env.py 가 이 값으로 연결한다
    try:
        yield url
    finally:
        asyncio.run(_admin(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def test_member_checks_fail_with_hint_until_filled(scratch_db: str) -> None:
    cfg = alembic_config()
    command.upgrade(cfg, AUTH_TABLES_REV)
    # 인증 칸이 비어 있는 기존 회원(인증 전에 만든 개발·측정 DB) + 이름이 겹치는 회원 + 탈퇴 회원
    asyncio.run(
        _execute(
            scratch_db,
            "INSERT INTO members (display_name, level) VALUES ('회원하나', 1), ('회원 하나', 2)",
            "INSERT INTO members (display_name, status, withdrawn_at) VALUES ('탈퇴 회원', 'withdrawn', now())",
        )
    )
    # 채우지 않으면 ② 가 자리 값 없이 안내와 함께 실패한다
    with pytest.raises(RuntimeError, match="인증 칸이 비어 있는 회원 2명 .*fill_auth_dev"):
        command.upgrade(cfg, "head")
    assert asyncio.run(_fill(scratch_db)) == 2
    command.upgrade(cfg, "head")
    rows = asyncio.run(
        _execute(
            scratch_db,
            "SELECT display_name, display_name_key, email, privacy_version, password_hash IS NOT NULL"
            " FROM members WHERE status = 'active' ORDER BY id",
        )
    )
    assert rows == [
        ("회원하나", "회원하나", "m1@example.test", "dev-notice", True),
        # 정규화 키가 겹치면 이름 뒤에 #id
        ("회원 하나#2", "회원하나#2", "m2@example.test", "dev-notice", True),
    ]
