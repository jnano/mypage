"""모델 공통 칸·제약 도우미. 관례는 설계도 §4 머리말."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Identity, func, text
from sqlalchemy.orm import Mapped, mapped_column

FALSE = text("false")
TRUE = text("true")
ZERO = text("0")
ONE = text("1")


def lit(value: str):
    """문자열 server_default — SQL 리터럴로 렌더한다."""
    return text(f"'{value}'")


def pk_id() -> Mapped[int]:
    return mapped_column(BigInteger, Identity(always=True), primary_key=True)


def created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


def updated_at() -> Mapped[datetime]:
    # 갱신은 트리거가 아니라 ORM 이 한다(§4 R4)
    return mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


def enum_check(column: str, values: tuple[str, ...]) -> CheckConstraint:
    allowed = ", ".join(f"'{v}'" for v in values)
    return CheckConstraint(f"{column} IN ({allowed})", name=f"{column}_enum")


def range_check(column: str, low: int, high: int | None = None) -> CheckConstraint:
    expr = f"{column} >= {low}" if high is None else f"{column} BETWEEN {low} AND {high}"
    return CheckConstraint(expr, name=f"{column}_range")
