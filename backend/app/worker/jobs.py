"""주기 작업 — 설계도 §3.2 표. 지금 대상 표가 있는 것만 둔다.

나중에 붙는 것: always 조회수 버퍼 반영(조회수 카운터).
각 작업은 한 번에 처리하는 양에 상한을 둬 트랜잭션을 짧게 한다(남은 것은 다음 회차).
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import and_, bindparam, delete, exists, func, literal_column, not_, or_, select, text, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.logs import redact_log_payload
from app.core.outbox import Event, enqueue
from app.files import storage
from app.models import (
    Attachment,
    Board,
    BoardDailyStat,
    Comment,
    IdempotencyKey,
    LoginSession,
    Member,
    ModerationLog,
    Notification,
    OutboxEvent,
    Post,
    PostViewDaily,
    PostViewOnce,
    RateLimitCounter,
    PasswordResetToken,
    Report,
    WithdrawnEmailMark,
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


async def cleanup_temp_uploads(db: AsyncSession) -> int:
    """글에 붙지 않은 채 24시간 지난 임시 업로드(§3.2). 행을 지우고 파일은 files.delete 이벤트로."""
    keys = (
        await db.execute(
            delete(Attachment)
            .where(
                Attachment.id.in_(
                    select(Attachment.id)
                    .where(Attachment.post_id.is_(None), Attachment.created_at < func.now() - text("interval '24 hours'"))
                    .limit(DELETE_BATCH)
                )
            )
            .returning(Attachment.storage_key)
        )
    ).scalars().all()
    if keys:
        await enqueue(db, [Event("files.delete", {"labels": [label for k in keys for label in storage.all_paths(k)]})])
    return len(keys)


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


REDACT_BATCH = 500


async def redact_moderation_logs(db: AsyncSession) -> int:
    """운영 기록 개인 칸 가림(§14.4) — 기록에 나오는 회원(행위자·작성자·대상 회원)이 탈퇴했거나 3년 지난 행."""
    withdrawn = Member.status == literal_column("'withdrawn'")

    def author_withdrawn(payload):
        return exists().where(Member.id == payload["author_id"].astext.cast(Member.id.type), withdrawn)

    rows = (
        await db.execute(
            select(ModerationLog.id, ModerationLog.before, ModerationLog.after)
            .where(
                ModerationLog.redacted_at.is_(None),
                or_(
                    ModerationLog.created_at < func.now() - text("interval '3 years'"),
                    exists().where(Member.id == ModerationLog.actor_id, withdrawn),
                    # 회원이 대상인 기록(가입 승인·이메일 변경 등)도 — 인증 설계도 §3.8
                    and_(
                        ModerationLog.target_type == literal_column("'member'"),
                        exists().where(Member.id == ModerationLog.target_id, withdrawn),
                    ),
                    author_withdrawn(ModerationLog.before),
                    author_withdrawn(ModerationLog.after),
                ),
            )
            .order_by(ModerationLog.id)
            .limit(REDACT_BATCH)
            .with_for_update(skip_locked=True)
        )
    ).all()
    if not rows:
        return 0
    logs = ModerationLog.__table__  # 행마다 값이 다른 UPDATE 를 executemany 로 — Core 표에 건다
    await db.execute(
        update(logs)
        .where(logs.c.id == bindparam("log_id"))
        .values(before=bindparam("b"), after=bindparam("a"), redacted_at=func.now()),
        [{"log_id": r.id, "b": redact_log_payload(r.before), "a": redact_log_payload(r.after)} for r in rows],
    )
    return len(rows)


# ── 인증 정리(인증 설계도 §8) ──


async def cleanup_sessions(db: AsyncSession) -> int:
    """만료·폐기 후 7일 지난 세션"""
    cutoff = func.now() - text("interval '7 days'")
    return await _delete_limited(
        db, LoginSession, or_(LoginSession.expires_at < cutoff, and_(LoginSession.revoked_at.is_not(None), LoginSession.revoked_at < cutoff))
    )


async def cleanup_reset_tokens(db: AsyncSession) -> int:
    """쓴·만료된 재설정 토큰"""
    return await _delete_limited(db, PasswordResetToken, or_(PasswordResetToken.used_at.is_not(None), PasswordResetToken.expires_at < func.now()))


async def cleanup_pending_signups(db: AsyncSession) -> int:
    """30일 지난 가입 대기(승인·거부되지 않은 신청)"""
    return await _delete_limited(
        db, Member, Member.status == literal_column("'pending'"), Member.created_at < func.now() - text("interval '30 days'")
    )


async def cleanup_withdrawn_marks(db: AsyncSession) -> int:
    """만료된 제재 회피 표시"""
    return await _delete_limited(db, WithdrawnEmailMark, WithdrawnEmailMark.expires_at < func.now())


JOBS: dict[str, Job] = {
    j.name: j
    for j in [
        Job("trash.purge", DAY, purge_trash),
        Job("notifications.cleanup", DAY, cleanup_notifications),
        Job("uploads.cleanup", HOUR, cleanup_temp_uploads),
        Job("idempotency.cleanup", HOUR, cleanup_idempotency),
        Job("rate_limit.cleanup", HOUR, cleanup_rate_limits),
        Job("view_records.cleanup", DAY, cleanup_view_records),
        Job("outbox.cleanup", DAY, cleanup_outbox),
        Job("board_daily_stats", HOUR, aggregate_board_daily_stats),
        Job("moderation_logs.redact", DAY, redact_moderation_logs),
        Job("sessions.cleanup", DAY, cleanup_sessions),
        Job("reset_tokens.cleanup", DAY, cleanup_reset_tokens),
        Job("pending_signups.cleanup", DAY, cleanup_pending_signups),
        Job("withdrawn_marks.cleanup", DAY, cleanup_withdrawn_marks),
    ]
}
