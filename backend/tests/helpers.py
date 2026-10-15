"""테스트 공용 도우미."""

from contextlib import contextmanager

from sqlalchemy import event

from app.db.session import engine

DEV_SECRET = "test-dev-secret-0123456789"


@contextmanager
def count_queries():
    """이 엔진으로 나간 SQL 문 수(§15 화면당 쿼리 수 예산 검사용)."""
    counter = {"n": 0, "sql": []}

    def on_execute(_conn, _cursor, statement, *_):
        counter["n"] += 1
        counter["sql"].append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", on_execute)
    try:
        yield counter
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", on_execute)


def as_member(member_id: int) -> dict[str, str]:
    return {"X-Dev-Member": f"{member_id}; key={DEV_SECRET}"}
