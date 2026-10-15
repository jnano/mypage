"""글 관리 API — 설계도 §6(bulk·휴지통·복원·영구 삭제·고정 순서), §14.3(통합 목록·승인 대기). 조치는 posts.moderation 한 곳."""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import exists, func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.scope import StaffScope
from app.api.admin import day_start, staff_scope
from app.auth.viewer import Viewer, get_viewer
from app.boards.admin import find_board
from app.db.session import SessionLocal, get_db
from app.models import Board, Post, PostStat, Report
from app.models.enums import POST_STATUSES
from app.posts import moderation
from app.posts.schemas import BulkRequest, PinnedOrder, ReasonBody

router = APIRouter()

POST_PAGE = 50


@router.post("/posts/bulk")
async def bulk(body: BulkRequest, viewer: Viewer = Depends(get_viewer)):
    async with SessionLocal() as db, db.begin():
        out = await moderation.apply(
            db, viewer, body.action, body.ids,
            board_id=body.board_id, category_ids=body.category_ids, min_view_level=body.min_view_level, reason=body.reason,
        )  # fmt: skip
    return out.body(done=len(body.ids), created=out.created)


async def _single(viewer: Viewer, action: str, post_id: int, reason: str | None) -> dict:
    async with SessionLocal() as db, db.begin():
        out = await moderation.apply(db, viewer, action, [post_id], reason=reason)
    return out.body(post={"id": post_id})


@router.delete("/posts/{post_id}")
async def trash_post(post_id: int, reason: str | None = Query(None, max_length=500), viewer: Viewer = Depends(get_viewer)):
    """휴지통으로(§6 DELETE = 휴지통). 작성자도 할 수 있다(post.trash)."""
    return await _single(viewer, "trash", post_id, reason)


@router.post("/posts/{post_id}/restore")
async def restore_post(post_id: int, body: ReasonBody | None = None, viewer: Viewer = Depends(get_viewer)):
    return await _single(viewer, "restore", post_id, body.reason if body else None)


@router.post("/posts/{post_id}/purge")
async def purge_post(post_id: int, body: ReasonBody | None = None, viewer: Viewer = Depends(get_viewer)):
    return await _single(viewer, "purge", post_id, body.reason if body else None)


@router.post("/posts/{post_id}/approve")
async def approve_post(post_id: int, body: ReasonBody | None = None, viewer: Viewer = Depends(get_viewer)):
    return await _single(viewer, "approve", post_id, body.reason if body else None)


@router.post("/posts/{post_id}/reject")
async def reject_post(post_id: int, body: ReasonBody, viewer: Viewer = Depends(get_viewer)):
    return await _single(viewer, "reject", post_id, body.reason)


@router.put("/boards/{slug}/pinned/order")
async def pinned_order(slug: str, body: PinnedOrder, viewer: Viewer = Depends(get_viewer)):
    async with SessionLocal() as db, db.begin():
        board = await find_board(db, slug)
        out = await moderation.order_pinned(db, viewer, board, body.ids)
    return out.body(ordered=True)


@router.get("/admin/posts")
async def admin_posts(
    board: str | None = Query(None, max_length=100, description="게시판 slug"),
    status: str = Query("all", description="all 또는 글 상태"),
    blinded: bool | None = None,
    secret: bool | None = None,
    reported: bool | None = None,
    pinned: bool | None = None,
    author_id: int | None = Query(None, gt=0),
    q: str | None = Query(None, min_length=1, max_length=100, description="제목에 든 말"),
    since: date | None = None,
    until: date | None = None,
    cursor: int | None = Query(None, gt=0),
    scope: StaffScope = Depends(staff_scope),
    db: AsyncSession = Depends(get_db),
):
    """통합 목록(§14.2) — 담당자는 자기 게시판만. 최신 id 순 키셋. 휴지통 글은 자동 정리 예정일을 함께."""
    open_reports = (
        select(func.count())
        .select_from(Report)
        .where(Report.status == literal_column("'open'"), Report.target_type == literal_column("'post'"), Report.target_id == Post.id)
        .scalar_subquery()
    )
    stmt = (
        select(  # post-clause: exempt — 관리 통합 목록(범위는 담당 게시판, 담당자는 상태와 무관하게 본다 §5.3)
            Post.id, Post.title, Post.status, Post.author_name_snapshot, Post.member_id, Post.is_guest, Post.published_at,
            Post.created_at, Post.trashed_at, Post.trashed_from_status, Post.is_pinned, Post.pin_order, Post.is_secret,
            Post.is_blinded, Post.min_view_level, Post.posted_as,
            Board.id.label("board_id"), Board.slug.label("board_slug"), Board.name.label("board_name"), Board.trash_retention_days,
            func.coalesce(PostStat.comment_count, 0).label("comments"), func.coalesce(PostStat.view_count, 0).label("views"),
            open_reports.label("reports"),
        )  # fmt: skip
        .join(Board, Board.id == Post.board_id)
        .outerjoin(PostStat, PostStat.post_id == Post.id)
        .where(scope.board_clause(Post.board_id))
        .order_by(Post.id.desc())
        .limit(POST_PAGE + 1)
    )
    if board is not None:
        stmt = stmt.where(Board.slug == board)
    if status != "all":
        stmt = stmt.where(Post.status == (status if status in POST_STATUSES else "__none__"))
    for column, value in ((Post.is_blinded, blinded), (Post.is_secret, secret), (Post.is_pinned, pinned)):
        if value is not None:
            stmt = stmt.where(column.is_(value))
    if reported is not None:
        has = exists().where(Report.status == literal_column("'open'"), Report.target_type == literal_column("'post'"), Report.target_id == Post.id)
        stmt = stmt.where(has if reported else ~has)
    if author_id is not None:
        stmt = stmt.where(Post.member_id == author_id)
    if q:
        stmt = stmt.where(Post.title.icontains(q, autoescape=True))
    if since is not None:
        stmt = stmt.where(Post.created_at >= day_start(since))
    if until is not None:
        stmt = stmt.where(Post.created_at < day_start(until))
    if cursor is not None:
        stmt = stmt.where(Post.id < cursor)
    rows = (await db.execute(stmt)).all()
    page = rows[:POST_PAGE]
    return {
        "items": [
            {
                "id": r.id,
                "title": r.title,
                "status": r.status,
                "board": {"id": r.board_id, "slug": r.board_slug, "name": r.board_name},
                "author": {"id": r.member_id, "name": r.author_name_snapshot, "guest": r.is_guest},
                "published_at": r.published_at.isoformat() if r.published_at else None,
                "created_at": r.created_at.isoformat(),
                "flags": {
                    "pinned": r.is_pinned, "pin_order": r.pin_order, "secret": r.is_secret, "blinded": r.is_blinded,
                    "min_view_level": r.min_view_level, "posted_as": r.posted_as,
                },  # fmt: skip
                "comments": r.comments,
                "views": r.views,
                "reports": r.reports,
                "trash": (
                    {
                        "trashed_at": r.trashed_at.isoformat(),
                        "from": r.trashed_from_status,
                        "purge_at": (r.trashed_at + timedelta(days=r.trash_retention_days)).isoformat() if r.trash_retention_days else None,
                    }
                    if r.trashed_at
                    else None
                ),
            }
            for r in page
        ],
        "next_cursor": page[-1].id if len(rows) > POST_PAGE else None,
    }


@router.get("/admin/pending")
async def pending(scope: StaffScope = Depends(staff_scope), db: AsyncSession = Depends(get_db)):
    """승인 대기열(§14.3) — 통합 목록의 status=pending 과 같다."""
    return await admin_posts(
        board=None, status="pending", blinded=None, secret=None, reported=None, pinned=None, author_id=None, q=None,
        since=None, until=None, cursor=None, scope=scope, db=db,
    )  # fmt: skip
