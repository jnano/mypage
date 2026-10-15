"""기반 표(작업자·멱등·요청 수 제한·검색어) — 설계도 §4.5"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CHAR,
    BigInteger,
    DateTime,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models._columns import ZERO, created_at, pk_id


class OutboxEvent(Base):
    """본 데이터와 같은 트랜잭션에 넣는 작업(§3.2). available_at 이 미래면 예약 작업."""

    __tablename__ = "outbox_events"

    id: Mapped[int] = pk_id()
    type: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    dedupe_key: Mapped[str | None] = mapped_column(String(100), unique=True)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    attempts: Mapped[int] = mapped_column(SmallInteger, server_default=ZERO)
    last_error: Mapped[str | None] = mapped_column(Text)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dead_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()


Index(
    "ix_outbox_events_pending",
    OutboxEvent.available_at,
    postgresql_where=text("processed_at IS NULL AND dead_at IS NULL"),
)


class WorkerSchedule(Base):
    __tablename__ = "worker_schedules"

    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    interval_sec: Mapped[int] = mapped_column(Integer)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IdempotencyKey(Base):
    """status_code IS NULL = 처리 중. 같은 키가 동시에 오면 409."""

    __tablename__ = "idempotency_keys"

    scope: Mapped[str] = mapped_column(String(80), primary_key=True)
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    request_hash: Mapped[str] = mapped_column(CHAR(64))
    status_code: Mapped[int | None] = mapped_column(SmallInteger)
    response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at()


class RateLimitCounter(Base):
    """UNLOGGED — 재시작 때 비워져도 되는 고정 창 카운터(§6)."""

    __tablename__ = "rate_limit_counters"
    __table_args__ = {"prefixes": ["UNLOGGED"]}

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, server_default=ZERO)


class SearchTerm(Base):
    __tablename__ = "search_terms"

    term: Mapped[str] = mapped_column(String(100), primary_key=True)
    count: Mapped[int] = mapped_column(BigInteger, server_default=ZERO)
    last_searched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SearchSynonym(Base):
    __tablename__ = "search_synonyms"

    term: Mapped[str] = mapped_column(String(100), primary_key=True)
    synonym: Mapped[str] = mapped_column(String(100), primary_key=True)
