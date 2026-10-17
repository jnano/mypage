"""최신순 키셋 커서(시각, id) — 알림함·내 목록이 함께 쓴다(설계도 §6.2·§7, 같은 모듈 하나 — §2.2).

꼴은 `ISO 시각|id`. 순서는 (시각 DESC, id DESC) — 같은 시각의 행도 빠짐·겹침 없이 넘긴다.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, tuple_

from app.core.problems import Problem


@dataclass(frozen=True)
class Cursor:
    created_at: datetime
    id: int

    def encode(self) -> str:
        return f"{self.created_at.isoformat()}|{self.id}"

    @staticmethod
    def decode(raw: str) -> "Cursor":
        at, _, nid = raw.partition("|")
        return Cursor(datetime.fromisoformat(at), int(nid))


def parse(raw: str | None) -> Cursor | None:
    """요청의 cursor — 없으면 None, 틀리면 422"""
    if not raw:
        return None
    try:
        return Cursor.decode(raw)
    except ValueError:
        raise Problem(422, "validation_error", "cursor 가 올바르지 않습니다") from None


def before(at_column, id_column, after: Cursor) -> ColumnElement[bool]:
    """(시각, id) < 커서 — 행 비교라 (시각 DESC, id DESC) 정렬과 짝이 맞는다"""
    return tuple_(at_column, id_column) < tuple_(after.created_at, after.id)


def cut(rows: Sequence[Any], size: int, at: str = "created_at", key: str = "id") -> tuple[list[Any], Cursor | None]:
    """size+1 개를 읽은 결과 → (앞 size 개, 다음 커서)"""
    rows = list(rows)
    if len(rows) <= size:
        return rows, None
    rows = rows[:size]
    last = rows[-1]
    return rows, Cursor(getattr(last, at), getattr(last, key))
