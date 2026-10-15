"""스키마 대조 — 설계도 §4(schema_spec.py) 와 models.py 메타데이터가 일대일인지 확인한다(§4.8)."""

import re

import pytest
from sqlalchemy import CheckConstraint, Column, Identity, Table, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.elements import TextClause

import app.db.models  # noqa: F401 — 모든 모델 등록
from app.db.base import Base
from tests.schema_spec import SPEC, T

PG = postgresql.dialect()
TYPE_ALIASES = {"timestamptz": "timestamp with time zone"}


def _norm(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def _parse_col(spec: str) -> dict:
    name, type_, *rest = spec.split()
    out = {
        "name": name,
        "type": TYPE_ALIASES.get(type_, type_),
        "nullable": False,
        "default": None,
        "identity": False,
        "enum": None,
        "range": None,
    }
    for token in rest:
        if token == "null":
            out["nullable"] = True
        elif token == "identity":
            out["identity"] = True
        elif token.startswith("="):
            out["default"] = token[1:]
        elif token.startswith("in("):
            out["enum"] = tuple(token[3:-1].split(","))
        elif token.startswith("range("):
            out["range"] = tuple(int(v) for v in token[6:-1].split(","))
        else:
            raise ValueError(f"알 수 없는 표기: {token!r} ({spec})")
    return out


def _col_type(col: Column) -> str:
    return col.type.compile(dialect=PG).lower()


def _col_default(col: Column) -> str | None:
    if col.server_default is None or isinstance(col.server_default, Identity):
        return None
    arg = col.server_default.arg
    if isinstance(arg, TextClause):
        return arg.text
    if isinstance(arg, str):
        return arg
    return str(arg.compile(dialect=PG))


def _expected_checks(name: str, spec: T) -> dict[str, str]:
    checks = dict(spec.checks)
    for c in map(_parse_col, spec.cols):
        if c["enum"]:
            allowed = ", ".join(f"'{v}'" for v in c["enum"])
            checks[f"{c['name']}_enum"] = f"{c['name']} IN ({allowed})"
        if c["range"]:
            low, *high = c["range"]
            checks[f"{c['name']}_range"] = (
                f"{c['name']} BETWEEN {low} AND {high[0]}" if high else f"{c['name']} >= {low}"
            )
    # 이름 규칙(app/db/base.py): ck_{표}_{이름}
    return {f"ck_{name}_{k}": _norm(v) for k, v in checks.items()}


def _actual_checks(table: Table) -> dict[str, str]:
    return {
        str(c.name): _norm(str(c.sqltext))
        for c in table.constraints
        if isinstance(c, CheckConstraint)
    }


def _index_signature(index) -> str:
    parts = [
        ", ".join(
            str(e.compile(dialect=PG)).replace(f"{index.table.name}.", "")
            for e in index.expressions
        )
    ]
    opts = index.dialect_options["postgresql"]
    if opts["where"] is not None:
        parts.append(f"where {_norm(str(opts['where']))}")
    if opts["using"]:
        parts.append(f"using {opts['using']}")
    if index.unique:
        parts.append("unique")
    return " | ".join(parts)


def test_table_set_matches() -> None:
    actual = set(Base.metadata.tables)
    expected = set(SPEC)
    assert actual - expected == set(), "설계도 §4 에 없는 표"
    assert expected - actual == set(), "모델에 없는 표"


@pytest.mark.parametrize("name", sorted(SPEC))
def test_columns(name: str) -> None:
    table = Base.metadata.tables[name]
    expected = {c["name"]: c for c in map(_parse_col, SPEC[name].cols)}
    assert list(table.columns.keys()) == list(expected), "칸 목록·순서가 설계도와 다르다"
    for col in table.columns:
        e = expected[col.name]
        assert _col_type(col) == e["type"], f"{name}.{col.name} 형"
        assert col.nullable == e["nullable"], f"{name}.{col.name} NULL 여부"
        assert _col_default(col) == e["default"], f"{name}.{col.name} 기본값"
        identity = col.identity is not None and bool(col.identity.always)
        assert identity == e["identity"], f"{name}.{col.name} IDENTITY"


@pytest.mark.parametrize("name", sorted(SPEC))
def test_primary_key(name: str) -> None:
    table = Base.metadata.tables[name]
    assert tuple(c.name for c in table.primary_key.columns) == SPEC[name].pk


@pytest.mark.parametrize("name", sorted(SPEC))
def test_foreign_keys(name: str) -> None:
    table = Base.metadata.tables[name]
    actual = {
        fk.parent.name: f"{fk.column.table.name} {fk.ondelete or 'NO ACTION'}"
        for fk in table.foreign_keys
    }
    assert actual == SPEC[name].fks


@pytest.mark.parametrize("name", sorted(SPEC))
def test_checks(name: str) -> None:
    table = Base.metadata.tables[name]
    assert _actual_checks(table) == _expected_checks(name, SPEC[name])


@pytest.mark.parametrize("name", sorted(SPEC))
def test_uniques(name: str) -> None:
    table = Base.metadata.tables[name]
    actual = {
        tuple(c.name for c in u.columns)
        for u in table.constraints
        if isinstance(u, UniqueConstraint)
    }
    assert actual == set(SPEC[name].uniques)


@pytest.mark.parametrize("name", sorted(SPEC))
def test_indexes(name: str) -> None:
    table = Base.metadata.tables[name]
    actual = {str(i.name): _index_signature(i) for i in table.indexes}
    expected = {k: _norm(v) for k, v in SPEC[name].indexes.items()}
    assert actual == expected


def test_spec_parser_rejects_unknown_token() -> None:
    # 대조군: 명세 오타가 조용히 통과하지 않는다
    with pytest.raises(ValueError):
        _parse_col("x integer nul")
