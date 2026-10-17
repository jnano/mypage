"""관리 API — 설계도 §14.3. 모든 경로가 관리 범위(app.admin.scope)를 거친다. 응답은 개인 데이터(캐시 안 함)."""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, literal_column, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin import settings as site_settings
from app.admin.scope import StaffScope, load_staff_scope
from app.admin.settings import SearchSettings
from app.auth.viewer import Viewer, get_viewer
from app.core.config import settings
from app.db.session import get_db
from app.models import Board, LevelRequest, Member, ModerationLog, OutboxEvent, Post, Report
from app.models.enums import MODERATION_TARGET_TYPES
from app.search import terms as search_terms

router = APIRouter(prefix="/admin")

LOG_PAGE = 50


def day_start(day: date) -> datetime:
    """사이트 시간대의 그날 0시(관리 화면의 날짜 거르기)."""
    return datetime.combine(day, time(), ZoneInfo(settings.site_time_zone))


async def staff_scope(viewer: Viewer = Depends(get_viewer), db: AsyncSession = Depends(get_db)) -> StaffScope:
    return await load_staff_scope(db, viewer)


@router.get("/summary")
async def summary(scope: StaffScope = Depends(staff_scope), db: AsyncSession = Depends(get_db)):
    """대시보드 배지(§14.2) — 신고 대기·승인 대기·오늘 새 글, 운영자는 실패 작업도. 쿼리 한 번."""
    open_reports = (
        select(func.count())
        .select_from(Report)
        .where(Report.status == literal_column("'open'"), scope.board_clause(Report.board_id))
        .scalar_subquery()
    )
    pending = (
        select(func.count())
        .select_from(Post)  # post-clause: exempt — 관리 집계(행을 내주지 않음), 범위는 담당 게시판
        .where(Post.status == literal_column("'pending'"), scope.board_clause(Post.board_id))
        .scalar_subquery()
    )
    today = (
        select(func.count())
        .select_from(Post)  # post-clause: exempt — 관리 집계(행을 내주지 않음), 범위는 담당 게시판
        .where(
            Post.status == literal_column("'published'"),
            Post.published_at >= func.date_trunc("day", func.now()),
            scope.board_clause(Post.board_id),
        )
        .scalar_subquery()
    )
    columns = [open_reports.label("reports"), pending.label("pending"), today.label("today")]
    if scope.is_admin:
        dead = select(func.count()).select_from(OutboxEvent).where(OutboxEvent.dead_at.is_not(None)).scalar_subquery()
        columns.append(dead.label("dead_jobs"))
        # 가입 대기·승급 대기(인증 설계도 §4.10-7) — 운영자만 처리한다
        signups = select(func.count()).select_from(Member).where(Member.status == literal_column("'pending'")).scalar_subquery()
        level_reqs = (
            select(func.count()).select_from(LevelRequest).where(LevelRequest.status == literal_column("'pending'")).scalar_subquery()
        )
        # 인증 경보(§7.5) — 지난 24시간
        alerts = (
            select(func.count())
            .select_from(ModerationLog)
            .where(ModerationLog.action.like("alert.%"), ModerationLog.created_at > func.now() - text("interval '24 hours'"))
            .scalar_subquery()
        )
        columns += [signups.label("signups"), level_reqs.label("level_requests"), alerts.label("alerts")]
    row = (await db.execute(select(*columns))).one()  # post-clause: exempt — 위 관리 집계 부분질의를 한 번에 읽음
    boards = (
        await db.execute(select(Board.id, Board.slug, Board.name).where(scope.board_clause(Board.id)).order_by(Board.sort_order, Board.id))
    ).all()
    # 지금 공개 화면에 나가는 인기 검색어(§9.1) — 이상한 말을 빨리 보고 검색 제외에 넣게(사용자 결정). 사이트 운영자만
    popular_terms = None
    if scope.is_admin:
        search = await site_settings.load(db, "search")
        assert isinstance(search, SearchSettings)
        popular_terms = await search_terms.popular(db, search)
    return {
        "viewer": {"member_id": scope.viewer.member_id, "is_admin": scope.is_admin},
        "boards": [{"id": b.id, "slug": b.slug, "name": b.name} for b in boards],
        "popular_terms": popular_terms,
        "badges": {
            "reports": row.reports,
            "pending": row.pending,
            "today_posts": row.today,
            "dead_jobs": row.dead_jobs if scope.is_admin else None,
            "signups": row.signups if scope.is_admin else None,
            "level_requests": row.level_requests if scope.is_admin else None,
            "alerts": row.alerts if scope.is_admin else None,
        },
    }


@router.get("/moderation-logs")
async def moderation_logs(
    actor_id: int | None = Query(None, gt=0),
    action: str | None = Query(None, max_length=40),
    target_type: str | None = Query(None, max_length=10),
    target_id: int | None = Query(None, gt=0),
    board_id: int | None = Query(None, gt=0),
    since: date | None = None,
    until: date | None = Query(None, description="이 날짜 전까지(그날 제외)"),
    cursor: int | None = Query(None, gt=0, description="이 id 보다 앞선 기록"),
    scope: StaffScope = Depends(staff_scope),
    db: AsyncSession = Depends(get_db),
):
    """운영 기록 조회(§14.2) — 운영자는 전체, 담당자는 자기 게시판 기록만. 최신순 키셋."""
    stmt = (
        select(ModerationLog, Member.display_name.label("actor_name"), Board.slug.label("board_slug"))
        .outerjoin(Member, Member.id == ModerationLog.actor_id)
        .outerjoin(Board, Board.id == ModerationLog.board_id)
        .where(scope.board_clause(ModerationLog.board_id))
        .order_by(ModerationLog.id.desc())
        .limit(LOG_PAGE + 1)
    )
    if target_type is not None and target_type not in MODERATION_TARGET_TYPES:
        target_type = "__none__"  # 모르는 종류는 빈 결과(오류 대신 필터로)
    filters = {
        ModerationLog.actor_id: actor_id,
        ModerationLog.action: action,
        ModerationLog.target_type: target_type,
        ModerationLog.target_id: target_id,
        ModerationLog.board_id: board_id,
    }
    for column, value in filters.items():
        if value is not None:
            stmt = stmt.where(column == value)
    if since is not None:
        stmt = stmt.where(ModerationLog.created_at >= day_start(since))
    if until is not None:
        stmt = stmt.where(ModerationLog.created_at < day_start(until))
    if cursor is not None:
        stmt = stmt.where(ModerationLog.id < cursor)
    rows = (await db.execute(stmt)).all()
    page = rows[:LOG_PAGE]
    return {
        "items": [
            {
                "id": log.id,
                "actor": {"id": log.actor_id, "name": actor_name},
                "board": {"id": log.board_id, "slug": board_slug} if log.board_id else None,
                "action": log.action,
                "target": {"type": log.target_type, "id": log.target_id},
                "before": log.before,
                "after": log.after,
                "reason": log.reason,
                "created_at": log.created_at.isoformat(),
                "redacted": log.redacted_at is not None,
            }
            for log, actor_name, board_slug in page
        ],
        "next_cursor": page[-1][0].id if len(rows) > LOG_PAGE else None,
    }
