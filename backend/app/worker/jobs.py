"""주기 작업 — 설계도 §3.2 표. 지금 대상 표가 있는 것만 둔다.

나중에 붙는 것: 임시 업로드 정리(첨부), always 조회수 버퍼 반영(조회수 카운터), 운영 기록 개인 칸 가림(관리 기능).
각 작업은 한 번에 처리하는 양에 상한을 둬 트랜잭션을 짧게 한다(남은 것은 다음 회차).
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import and_, delete, func, literal_column, not_, select, text, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Board,
    BoardDailyStat,
    Comment,
    IdempotencyKey,
    Notification,
    OutboxEvent,
    Post,
    PostViewDaily,
    PostViewOnce,
    RateLimitCounter,
    Report,
)
from app.posts.purge import purge_posts

HOUR = 3600
DAY = 86400
TRASH_BATCH = 500
DELETE_BATCH = 5000
NOTIFICATIONS_PER_MEMBER = 1000


@dataclass(frozen=True)
class Job:
    name: str
    interval_sec: int
    run: Callable[[AsyncSession], Awaitable[int]]


async def _delete_limited(db: AsyncSession, model, *where) -> int:
    """조건에 맞는 행을 최대 DELETE_BATCH 개 지운다(ctid 대신 PK 부분질의 — 공식 SQL 만 쓴다)."""
    pk = list(model.__table__.primary_key.columns)
    victims = select(*pk).where(*where).limit(DELETE_BATCH)  # post-clause: exempt — 정리 작업이 지울 행의 PK 만 고른다
    if len(pk) == 1:
        result = await db.execute(delete(model).where(pk[0].in_(victims)))
    else:
        result = await db.execute(delete(model).where(tuple_(*pk).in_(victims)))
    return result.rowcount or 0


async def purge_trash(db: AsyncSession) -> int:
    """휴지통 자동 정리 — 게시판 trash_retention_days 가 지난 글을 영구 삭제(§4.6)."""
    ids = (
        await db.execute(
            select(Post.id)  # post-clause: exempt — 휴지통 정리 대상 선정(작업자)
            .join(Board, Board.id == Post.board_id)
            .where(
                Post.status == literal_column("'trashed'"),
                Board.trash_retention_days.is_not(None),
                Post.trashed_at < func.now() - func.make_interval(0, 0, 0, Board.trash_retention_days),
            )
            .order_by(Post.trashed_at)
            .limit(TRASH_BATCH)
        )
    ).scalars().all()
    return await purge_posts(db, list(ids))


async def cleanup_notifications(db: AsyncSession) -> int:
    """읽음 90일·안 읽음 180일 지난 알림, 사람당 최신 1,000건을 넘는 알림(§3.2)."""
    removed = await _delete_limited(
        db,
        Notification,
        (Notification.read_at.is_not(None) & (Notification.read_at < func.now() - text("interval '90 days'")))
        | (Notification.read_at.is_(None) & (Notification.created_at < func.now() - text("interval '180 days'"))),
    )
    ranked = (
        select(
            Notification.id,
            func.row_number()
            .over(partition_by=Notification.recipient_id, order_by=(Notification.created_at.desc(), Notification.id.desc()))
            .label("rn"),
        )
    ).subquery()
    over = select(ranked.c.id).where(ranked.c.rn > NOTIFICATIONS_PER_MEMBER).limit(DELETE_BATCH)
    result = await db.execute(delete(Notification).where(Notification.id.in_(over)))
    return removed + (result.rowcount or 0)


async def cleanup_idempotency(db: AsyncSession) -> int:
    return await _delete_limited(db, IdempotencyKey, IdempotencyKey.created_at < func.now() - text("interval '24 hours'"))


async def cleanup_rate_limits(db: AsyncSession) -> int:
    # 가장 긴 창이 하루를 넘지 않는다(core.rate_limit.LIMITS)
    return await _delete_limited(db, RateLimitCounter, RateLimitCounter.window_start < func.now() - text("interval '1 day'"))


async def cleanup_view_records(db: AsyncSession) -> int:
    """daily 기록은 하루, 비회원 once 기록은 30일(§3.2). 회원 once(m:…)는 남긴다."""
    daily = await _delete_limited(db, PostViewDaily, PostViewDaily.view_date < func.current_date() - 1)
    once = await _delete_limited(
        db,
        PostViewOnce,
        not_(PostViewOnce.viewer_key.startswith("m:")),
        PostViewOnce.created_at < func.now() - text("interval '30 days'"),
    )
    return daily + once


async def cleanup_outbox(db: AsyncSession) -> int:
    """처리 후 7일 지난 이벤트(§3.2). 실패(dead) 이벤트는 운영자가 보도록 남긴다."""
    return await _delete_limited(
        db, OutboxEvent, OutboxEvent.processed_at < func.now() - text("interval '7 days'")
    )


async def aggregate_board_daily_stats(db: AsyncSession) -> int:
    """오늘·어제의 게시판별 글·댓글·신고 수(§4.2 board_daily_stats). 조회수 칸은 조회수 카운터와 함께 채운다."""
    days = select(func.current_date().label("day")).union_all(select((func.current_date() - 1).label("day"))).subquery()
    posts = (
        select(Post.board_id, func.date(Post.published_at).label("day"), func.count().label("n"))  # post-clause: exempt — 집계(행을 내주지 않음)
        .where(Post.status == literal_column("'published'"), Post.published_at >= func.current_date() - 1, Post.published_at < func.current_date() + 1)
        .group_by(Post.board_id, func.date(Post.published_at))
    ).subquery()
    comments = (
        select(Post.board_id, func.date(Comment.created_at).label("day"), func.count().label("n"))  # post-clause: exempt — 집계(행을 내주지 않음)
        .join(Post, Post.id == Comment.post_id)
        .where(Comment.created_at >= func.current_date() - 1)
        .group_by(Post.board_id, func.date(Comment.created_at))
    ).subquery()
    reports = (
        select(Report.board_id, func.date(Report.created_at).label("day"), func.count().label("n"))
        .where(Report.board_id.is_not(None), Report.created_at >= func.current_date() - 1)
        .group_by(Report.board_id, func.date(Report.created_at))
    ).subquery()
    grid = (
        select(
            Board.id.label("board_id"),
            days.c.day,
            func.coalesce(posts.c.n, 0).label("posts"),
            func.coalesce(comments.c.n, 0).label("comments"),
            func.coalesce(reports.c.n, 0).label("reports"),
        )
        .select_from(Board)
        .join(days, literal_column("true"))
        .outerjoin(posts, and_(posts.c.board_id == Board.id, posts.c.day == days.c.day))
        .outerjoin(comments, and_(comments.c.board_id == Board.id, comments.c.day == days.c.day))
        .outerjoin(reports, and_(reports.c.board_id == Board.id, reports.c.day == days.c.day))
    )
    stmt = insert(BoardDailyStat).from_select(["board_id", "day", "posts", "comments", "reports"], grid)
    stmt = stmt.on_conflict_do_update(
        index_elements=["board_id", "day"],
        set_={"posts": stmt.excluded.posts, "comments": stmt.excluded.comments, "reports": stmt.excluded.reports},
    )
    result = await db.execute(stmt)
    return result.rowcount or 0


JOBS: dict[str, Job] = {
    j.name: j
    for j in [
        Job("trash.purge", DAY, purge_trash),
        Job("notifications.cleanup", DAY, cleanup_notifications),
        Job("idempotency.cleanup", HOUR, cleanup_idempotency),
        Job("rate_limit.cleanup", HOUR, cleanup_rate_limits),
        Job("view_records.cleanup", DAY, cleanup_view_records),
        Job("outbox.cleanup", DAY, cleanup_outbox),
        Job("board_daily_stats", HOUR, aggregate_board_daily_stats),
    ]
}
