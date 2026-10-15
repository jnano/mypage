"""마이그레이션 — 모델과 실제 DB 가 같은지(§4.8 의 DB 쪽). downgrade/upgrade 는 conftest 가 매번 돈다."""

import pytest
from alembic import command
from sqlalchemy import CheckConstraint, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base
from tests.conftest import alembic_config
from tests.schema_spec import SPEC

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
