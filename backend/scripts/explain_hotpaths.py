"""핫패스 실행 계획 — 설계도 §15.3. 앱 쿼리 함수가 만든 문장을 그대로 EXPLAIN 한다.

각 문장을 asyncpg 방언으로 컴파일해 PREPARE 하고, 같은 세션 안에서만
plan_cache_mode = force_custom_plan / force_generic_plan 으로 EXPLAIN (ANALYZE, BUFFERS) EXECUTE 를 6회 이상 돌린다.
전역 설정은 바꾸지 않는다(§2.2 P4). 연결은 풀 밖의 전용 연결(NullPool)이라 세션 설정이 앱으로 새지 않는다.

실행: cd backend && DATABASE_URL=…/mypage_bench uv run python -m scripts.explain_hotpaths --out <보고서 경로>
"""

import argparse
import asyncio
import json
import statistics
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.auth.viewer import GUEST, Viewer, load_viewer
from app.blocks import frame
from app.core.config import settings
from app.models import Board, BoardModerator, Member, Post
from app.permissions import load_board_role
from app.posts import queries
from app.search.backend import backend, parse_query

RUNS = 6


def _literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, datetime):
        return f"'{value.isoformat()}'::timestamptz"
    if isinstance(value, list | tuple):
        return "ARRAY[" + ", ".join(_literal(v) for v in value) + "]::text[]"
    return "'" + str(value).replace("'", "''") + "'"


def _compile(stmt, dialect) -> tuple[str, list[Any]]:
    compiled = stmt.compile(dialect=dialect, compile_kwargs={"render_postcompile": True})
    params = compiled.construct_params()
    return compiled.string, [params[name] for name in compiled.positiontup]


def _walk(plan: dict, out: list[str]) -> None:
    label = plan["Node Type"]
    if "Index Name" in plan:
        label += f"({plan['Index Name']})"
    out.append(label)
    for child in plan.get("Plans", []):
        _walk(child, out)


@dataclass
class Measured:
    mode: str
    exec_ms: list[float]
    plan_ms: list[float]
    nodes: list[str]

    @property
    def median(self) -> float:
        return statistics.median(self.exec_ms)


async def explain(conn: AsyncConnection, name: str, stmt, dialect) -> dict[str, Measured]:
    sql, params = _compile(stmt, dialect)
    await conn.exec_driver_sql(f"PREPARE hp AS {sql}")
    args = ", ".join(_literal(p) for p in params)
    execute = f"EXECUTE hp({args})" if params else "EXECUTE hp"
    result = {}
    for mode in ("force_custom_plan", "force_generic_plan"):
        await conn.exec_driver_sql(f"SET plan_cache_mode = {mode}")
        exec_ms, plan_ms, nodes = [], [], []
        for _ in range(RUNS):
            raw = (await conn.exec_driver_sql(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {execute}")).scalar_one()
            doc = (json.loads(raw) if isinstance(raw, str) else raw)[0]
            exec_ms.append(doc["Execution Time"])
            plan_ms.append(doc.get("Planning Time", 0.0))
            nodes = []
            _walk(doc["Plan"], nodes)
        result[mode] = Measured(mode, exec_ms, plan_ms, nodes)
    await conn.exec_driver_sql("RESET plan_cache_mode")
    await conn.exec_driver_sql("DEALLOCATE hp")  # 내가 만든 것만(asyncpg 의 준비된 문장은 건드리지 않는다)
    return result


async def purge_explain(conn: AsyncConnection, post_id: int) -> list[str]:
    """글 영구 삭제의 FK 비용(트리거 시간) — 트랜잭션 안에서 지우고 되돌린다. 결정은 영구 삭제 단계에서."""
    lines = []
    await conn.rollback()  # 앞 측정의 자동 트랜잭션을 닫는다
    for _ in range(RUNS):
        raw = (await conn.exec_driver_sql(f"EXPLAIN (ANALYZE, FORMAT JSON) DELETE FROM posts WHERE id = {int(post_id)}")).scalar_one()
        await conn.rollback()  # 지운 것을 되돌린다
        doc = (json.loads(raw) if isinstance(raw, str) else raw)[0]
        lines = [f"{t['Trigger Name']} on {t.get('Relation', '?')}: {t['Time']:.2f}ms × {t['Calls']}" for t in doc.get("Triggers", [])]
        lines.insert(0, f"Execution {doc['Execution Time']:.2f}ms")
    return lines


async def build_cases(db: AsyncSession) -> tuple[list[tuple[str, Callable[[], Any]]], int]:
    boards = {b.slug: b for b in (await db.execute(select(Board))).scalars()}
    free, consult, members = boards["free"], boards["consult"], boards["members"]
    member_id = (await db.execute(select(Member.id).where(Member.level == 2, Member.is_admin.is_(False)).limit(1))).scalar_one()
    member = await load_viewer(member_id)
    mod_id = (await db.execute(select(BoardModerator.member_id).where(BoardModerator.board_id == free.id))).scalar_one()
    mod = await load_viewer(mod_id)
    guest_role = await load_board_role(db, GUEST, free.id)
    member_consult = await load_board_role(db, member, consult.id)
    member_members = await load_board_role(db, member, members.id)
    mod_role = await load_board_role(db, mod, free.id)

    mid = (await db.execute(
        select(Post.id, Post.published_at).where(Post.board_id == free.id, Post.status == "published", Post.is_pinned.is_(False))  # post-clause: exempt — 측정 표본 고르기
        .order_by(Post.published_at.desc()).offset(30000).limit(1)
    )).one()  # fmt: skip
    page_ids = list((await db.execute(
        select(Post.id).where(Post.board_id == consult.id, Post.status == "published")  # post-clause: exempt — 측정 표본 고르기
        .order_by(Post.published_at.desc()).limit(20)
    )).scalars())  # fmt: skip

    def lst(viewer: Viewer, role, board, page: int):
        return queries.board_list_statements(viewer, role, board, page=page, per_page=20)

    def search(viewer: Viewer, q: str, scope="all"):
        return backend.statements(viewer, parse_query(q, board_id=None, scope=scope, page=1))

    return [
        ("목록 1쪽 · 비회원 · free", lambda: lst(GUEST, guest_role, free, 1).rows),
        ("목록 깊은 쪽(250) · 비회원 · free", lambda: lst(GUEST, guest_role, free, 250).rows),
        ("목록 마지막 쪽(500) · 비회원 · free", lambda: lst(GUEST, guest_role, free, 500).rows),
        ("목록 개수(상한 10001) · 비회원 · free", lambda: lst(GUEST, guest_role, free, 1).count),
        ("고정 글 띠 · free", lambda: lst(GUEST, guest_role, free, 1).pinned),
        ("목록 1쪽 · 담당자 · free", lambda: lst(mod, mod_role, free, 1).rows),
        ("목록 1쪽 · 회원 · consult(hide)", lambda: lst(member, member_consult, consult, 1).rows),
        ("목록 1쪽 · 회원(레벨2) · members", lambda: lst(member, member_members, members, 1).rows),
        ("이전·다음 글 · 비회원", lambda: queries.neighbors_statement(GUEST, free.id, mid.published_at, mid.id)),
        ("hide 판정 EXISTS · consult", lambda: queries.has_restricted_statement(consult.id)),
        ("개인 조각 글 20개 · 회원 · consult", lambda: queries.posts_for_state_statement(member, consult.id, page_ids)),
        ("글 보기 한 건", lambda: queries.post_view_statement(mid.id)),
        ("검색 흔한 단어 '회의' · 비회원", lambda: search(GUEST, "회의")[0]),
        ("검색 흔한 단어 '회의' 개수 · 비회원", lambda: search(GUEST, "회의")[1]),
        ("검색 드문 단어 '분기결산' · 비회원", lambda: search(GUEST, "분기결산")[0]),
        ("검색 띄어쓰기 '회의 자료' · 비회원", lambda: search(GUEST, "회의 자료")[0]),
        ("검색 흔한 단어 '안내' · 회원", lambda: search(member, "안내")[0]),
        ("검색 제목만 '모집' · 비회원", lambda: search(GUEST, "모집", "title")[0]),
        # 홈블록 틀 묶음(§5.2) — 최근 글·댓글 블록. 댓글이 한 게시판에 몰린 측정 DB 라 '댓글 없는 게시판'이 최악(M-1)
        ("홈블록 최근 글 · 전 게시판 20 + 고정", lambda: frame.recent_posts_statement({b.id: 20 for b in boards.values()}, True)),
        ("홈블록 최근 댓글 · free 20", lambda: frame.recent_comments_statement({free.id: 20})),
        ("홈블록 최근 댓글 · 댓글 없는 consult 20", lambda: frame.recent_comments_statement({consult.id: 20})),
        ("홈블록 최근 댓글 · 전 게시판 20", lambda: frame.recent_comments_statement({b.id: 20 for b in boards.values()})),
    ], mid.id


async def main(out: str) -> None:
    name = make_url(settings.database_url).database or ""
    if not name.endswith("_bench"):
        raise SystemExit(f"측정 전용 DB 에서만 실행합니다: {name}")
    eng = create_async_engine(settings.database_url, poolclass=NullPool)
    lines = [f"# 핫패스 실행 계획 — {datetime.now().isoformat(timespec='minutes')}", "", f"DB `{name}`, 각 {RUNS}회, 실행 시간 중앙값(ms).", ""]
    lines += ["| 경로 | custom ms | generic ms | generic 계획(노드) |", "|---|---:|---:|---|"]
    details = []
    async with AsyncSession(eng) as db:
        cases, purge_id = await build_cases(db)
    async with eng.connect() as conn:
        for label, make in cases:
            stmt = make()
            res = await explain(conn, label, stmt, eng.dialect)
            c, g = res["force_custom_plan"], res["force_generic_plan"]
            lines.append(f"| {label} | {c.median:.2f} | {g.median:.2f} | {' > '.join(g.nodes[:6])} |")
            details.append(f"### {label}\n- custom: {' > '.join(c.nodes)}\n- generic: {' > '.join(g.nodes)}\n- custom 실행 {[round(x, 2) for x in c.exec_ms]}\n- generic 실행 {[round(x, 2) for x in g.exec_ms]}\n")
            print(f"{label}: custom {c.median:.2f}ms generic {g.median:.2f}ms")
        purge = await purge_explain(conn, purge_id)
    await eng.dispose()
    lines += ["", "## 글 영구 삭제(FK 연쇄, 되돌림) — 결정은 영구 삭제 단계", "", *[f"- {l}" for l in purge], "", "## 계획 상세", "", *details]
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"→ {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    asyncio.run(main(parser.parse_args().out))
