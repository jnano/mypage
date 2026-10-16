"""글 반응 — 설계도 §6.1. 추천·스크랩(상태 지정)과 조회·공유 카운터.

카운터 정합: 반응 행 삽입·삭제가 행을 돌려줄 때만 같은 트랜잭션에서 post_stats 를 ±1 — 최종 판정은 PK 다.
조회의 once·daily 는 단독 짧은 트랜잭션, always 는 API 프로세스 메모리 버퍼(view_buffer)에 더한다.
"""

import base64
import hashlib
import logging
import re
from typing import Literal

from sqlalchemy import Row, delete, exists, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.viewer import Viewer
from app.core import rate_limit
from app.core.config import settings
from app.core.problems import Problem
from app.db.session import SessionLocal, engine
from app.models import Board, Post, PostReaction, PostScrap, PostStat, PostViewDaily, PostViewOnce
from app.permissions import can, load_board_role
from app.posts import view_buffer

logger = logging.getLogger(__name__)

Kind = Literal["like", "scrap"]

# 조회 쿠키 값 — 임의 32바이트의 base64url(패딩 없음) 43자. Route Handler 가 만든다(§6.1).
# 같은 규칙이 프런트 lib/auth/cookies.ts 의 VIEW_TOKEN 에도 있다 — 바꾸면 둘을 함께(시험 표본도 같은 꼴)
VIEW_TOKEN = re.compile(r"^[A-Za-z0-9_-]{43}$")

# 판정에 필요한 칸만 — 조회 신호마다 본문을 읽지 않는다
_JUDGE_COLUMNS = (
    Post.id,
    Post.board_id,
    Post.member_id,
    Post.is_guest,
    Post.status,
    Post.is_secret,
    Post.is_blinded,
    Post.min_view_level,
)


async def _load(db: AsyncSession, post_id: int) -> tuple[Row, Board] | None:
    row = (
        await db.execute(
            select(*_JUDGE_COLUMNS, Board).join(Board, Board.id == Post.board_id).where(Post.id == post_id)  # post-clause: exempt — 한 건, 호출부가 can() 판정
        )
    ).one_or_none()
    return None if row is None else (row, row.Board)


def _not_found() -> Problem:
    return Problem(404, "post_not_found", "글을 찾을 수 없습니다")


def _require_member(viewer: Viewer) -> int:
    if viewer.member_id is None:
        raise Problem(401, "login_required", "로그인이 필요합니다")
    return viewer.member_id


def _table(kind: Kind):
    return (PostReaction, PostStat.like_count) if kind == "like" else (PostScrap, PostStat.scrap_count)


def _body(kind: Kind, on: bool, count: int | None) -> dict:
    state, count_key = ("liked", "like_count") if kind == "like" else ("scrapped", "scrap_count")
    return {state: on} if count is None else {state: on, count_key: count}


async def _write_and_count(stmt, post_id: int, column, delta: int, *, current: bool = True) -> int:
    """반응 행 쓰기(stmt — RETURNING post_id)와 카운터 ±1 을 **autocommit 한 문장(CTE)** 으로.

    post_stats 행 잠금이 앱 ↔ DB 왕복(UPDATE 뒤 COMMIT 을 보내기까지)에 걸리지 않게 한다 — 한 트랜잭션에 두 문장을 보내면
    동시 요청으로 이벤트 루프가 바쁠 때 그 사이가 늘어 같은 글의 요청이 줄을 섰다(측정 §6.1: 한 글 동시 20 p95 80~225ms).
    행이 생기거나 지워졌을 때만 카운터를 바꾼다(EXISTS) — 최종 판정은 PK.
    """
    changed = stmt.cte("changed")
    value = column + 1 if delta > 0 else func.greatest(column - 1, 0)
    bump = (
        update(PostStat)
        .where(PostStat.post_id == post_id, exists(select(changed.c.post_id)))
        .values({column.key: value})
        .returning(column)
    )
    async with engine.connect() as conn:
        conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        got = (await conn.execute(bump)).scalar_one_or_none()
        if got is None and current:  # 바뀐 행이 없음(이미 그 상태) — 지금 값
            got = (await conn.execute(select(column).where(PostStat.post_id == post_id))).scalar_one_or_none()
            if got is None:
                logger.warning("post_stats 행이 없는 글: %s", post_id)
    return got or 0


async def _judge(viewer: Viewer, post_id: int):
    """(post, board, role) 또는 None — 읽기만, 잠그지 않는다"""
    async with SessionLocal() as db:
        found = await _load(db, post_id)
        if found is None:
            return None
        post, board = found
        return post, board, await load_board_role(db, viewer, board.id)


async def turn_on(viewer: Viewer, post_id: int, kind: Kind) -> dict:
    """켜기(PUT) — 이미 켜져 있으면 수를 바꾸지 않고 지금 값"""
    member_id = _require_member(viewer)
    await rate_limit.hit("post.react", f"m:{member_id}")
    table, column = _table(kind)
    judged = await _judge(viewer, post_id)
    if judged is None:
        raise _not_found()
    post, board, role = judged
    if not can(viewer, role, "post.read", board, post):
        raise _not_found()  # 있음을 드러내지 않는다 — post.read 거부와 같은 응답
    if post.status != "published":
        raise Problem(409, "not_published", "공개된 글에만 할 수 있습니다")
    if not can(viewer, role, "post.react", board, post):  # pragma: no cover — 위 두 조건과 회원 확인이 같은 판정
        raise _not_found()
    stmt = insert(table).values(post_id=post_id, member_id=member_id).on_conflict_do_nothing().returning(table.post_id)
    return _body(kind, True, await _write_and_count(stmt, post_id, column, +1))


async def turn_off(viewer: Viewer, post_id: int, kind: Kind) -> dict:
    """끄기(DELETE) — post.read 로 거부하지 않는다. 읽을 수 있는 글일 때만 수를 싣는다(§6.1)"""
    member_id = _require_member(viewer)
    await rate_limit.hit("post.react", f"m:{member_id}")
    table, column = _table(kind)
    judged = await _judge(viewer, post_id)
    readable = judged is not None and can(viewer, judged[2], "post.read", judged[1], judged[0])
    stmt = delete(table).where(table.post_id == post_id, table.member_id == member_id).returning(table.post_id)
    # 읽을 수 없는(또는 없는) 글은 지금 값을 읽지 않는다 — 없는 글마다 'post_stats 행 없음' 경고가 쌓이지 않게(검토 묶음A N-3)
    count = await _write_and_count(stmt, post_id, column, -1, current=readable)
    return _body(kind, False, count if readable else None)


# ── 카운터 ──────────────────────────────────────────────


def viewer_key(viewer: Viewer, view_token: str | None) -> str | None:
    """회원 m:{id}, 비회원 g:{base64url(sha256(쿠키))} — 45자, varchar(64) 에 맞춘다(§6.1)"""
    if viewer.member_id is not None:
        return f"m:{viewer.member_id}"
    if view_token is None or not VIEW_TOKEN.match(view_token):
        return None
    digest = hashlib.sha256(view_token.encode()).digest()
    return "g:" + base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def site_today():
    """사이트 시간대의 오늘(§3.7) — DB 세션 시간대의 current_date 가 아니다. daily 기록과 그 정리가 같은 규칙을 쓴다"""
    return func.date(func.timezone(settings.site_time_zone, func.now()))


async def _countable(viewer: Viewer, post_id: int) -> Board | None:
    judged = await _judge(viewer, post_id)
    if judged is None:
        return None
    post, board, role = judged
    # 운영자는 can() 을 맨 앞에서 통과하므로 공개 상태를 여기서 따로 본다 — 초안·대기 글의 조회를 세지 않는다(검토 묶음A N-2)
    if post.status != "published":
        return None
    return board if can(viewer, role, "post.count", board, post) else None


async def record_view(viewer: Viewer, post_id: int, ip: str, view_token: str | None) -> None:
    """조회 신호 — 셌는지 알리지 않는다(호출부는 늘 204). 한도를 넘으면 429"""
    if not await rate_limit.allow("post.view", ip):
        raise Problem(429, "rate_limited", "요청이 너무 많습니다")
    key = viewer_key(viewer, view_token)
    if key is None:
        return
    board = await _countable(viewer, post_id)
    if board is None:
        return
    if board.view_count_mode == "always":
        view_buffer.add(post_id)
        return
    if board.view_count_mode == "once":
        stmt = insert(PostViewOnce).values(post_id=post_id, viewer_key=key)
    else:
        stmt = insert(PostViewDaily).values(post_id=post_id, viewer_key=key, view_date=site_today())
    await _write_and_count(stmt.on_conflict_do_nothing().returning(stmt.table.c.post_id), post_id, PostStat.view_count, +1, current=False)


async def record_share(viewer: Viewer, post_id: int, ip: str) -> None:
    """공유 — 같은 IP·글은 시간당 3회까지만 센다. 정확한 수를 약속하지 않는다(§6.1)"""
    if not await rate_limit.allow("post.share", f"{ip}:{post_id}"):
        return
    board = await _countable(viewer, post_id)
    if board is None or not board.allow_share:
        return
    async with engine.connect() as conn:
        conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        await conn.execute(update(PostStat).where(PostStat.post_id == post_id).values(share_count=PostStat.share_count + 1))
