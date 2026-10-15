"""댓글 관리·신고 처리·제재 API — 설계도 §14.2·§14.3. 범위는 StaffScope(담당자는 자기 게시판)."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin import sanctions
from app.admin.scope import StaffScope
from app.api.admin import staff_scope
from app.comments import moderation as comment_moderation
from app.db.session import SessionLocal, get_db
from app.models import Board, Comment, Post
from app.models.enums import REPORT_STATUSES
from app.reports import service as reports
from app.reports.schemas import CommentBulk, ReportResolve, SanctionCreate

router = APIRouter()

COMMENT_PAGE = 50


@router.get("/admin/reports")
async def report_queue(status: str = Query("open"), scope: StaffScope = Depends(staff_scope), db: AsyncSession = Depends(get_db)):
    return {"items": await reports.queue(db, scope, status if status in REPORT_STATUSES else "open")}


@router.post("/admin/reports/{report_id}/resolve")
async def resolve_report(report_id: int, body: ReportResolve, scope: StaffScope = Depends(staff_scope)):
    async with SessionLocal() as db, db.begin():
        return await reports.resolve(db, scope, report_id, body)


@router.get("/admin/comments")
async def admin_comments(
    board: str | None = Query(None, max_length=100),
    blinded: bool | None = None,
    author_id: int | None = Query(None, gt=0),
    q: str | None = Query(None, min_length=1, max_length=100),
    cursor: int | None = Query(None, gt=0),
    scope: StaffScope = Depends(staff_scope),
    db: AsyncSession = Depends(get_db),
):
    """댓글 통합 목록(§14.2) — 지운 댓글은 빼고, 최신순 키셋."""
    stmt = (
        select(  # post-clause: exempt — 관리 통합 목록(범위는 담당 게시판)
            Comment.id, Comment.post_id, Comment.member_id, Comment.author_name_snapshot, Comment.content, Comment.is_blinded,
            Comment.blind_source, Comment.created_at, Post.title, Board.slug, Board.name,
        )  # fmt: skip
        .join(Post, Post.id == Comment.post_id)
        .join(Board, Board.id == Post.board_id)
        .where(Comment.status == literal_column("'published'"), scope.board_clause(Post.board_id))
        .order_by(Comment.id.desc())
        .limit(COMMENT_PAGE + 1)
    )
    if board is not None:
        stmt = stmt.where(Board.slug == board)
    if blinded is not None:
        stmt = stmt.where(Comment.is_blinded.is_(blinded))
    if author_id is not None:
        stmt = stmt.where(Comment.member_id == author_id)
    if q:
        stmt = stmt.where(Comment.content.icontains(q, autoescape=True))
    if cursor is not None:
        stmt = stmt.where(Comment.id < cursor)
    rows = (await db.execute(stmt)).all()
    page = rows[:COMMENT_PAGE]
    return {
        "items": [
            {
                "id": r.id,
                "post": {"id": r.post_id, "title": r.title},
                "board": {"slug": r.slug, "name": r.name},
                "author": {"id": r.member_id, "name": r.author_name_snapshot},
                "content": r.content,
                "blinded": r.is_blinded,
                "blind_source": r.blind_source,
                "created_at": r.created_at.isoformat(),
            }
            for r in page
        ],
        "next_cursor": page[-1].id if len(rows) > COMMENT_PAGE else None,
    }


@router.post("/comments/bulk")
async def comments_bulk(body: CommentBulk, scope: StaffScope = Depends(staff_scope)):
    async with SessionLocal() as db, db.begin():
        rows = await comment_moderation.load_comments(db, scope.viewer, body.ids)
        invalidate = await comment_moderation.apply(db, scope.viewer, body.action, rows, body.reason)
    return {"done": len(rows), "invalidate": invalidate}


@router.get("/admin/sanctions")
async def list_sanctions(
    member_id: int | None = Query(None, gt=0),
    active: bool = True,
    scope: StaffScope = Depends(staff_scope),
    db: AsyncSession = Depends(get_db),
):
    return {"items": await sanctions.list_sanctions(db, scope, member_id=member_id, active_only=active)}


@router.post("/admin/sanctions", status_code=201)
async def create_sanction(body: SanctionCreate, scope: StaffScope = Depends(staff_scope)):
    async with SessionLocal() as db, db.begin():
        sanction_id = await sanctions.create(
            db, scope, member_id=body.member_id, board_id=None if body.site_wide else body.board_id,
            actions=body.actions, days=body.days, reason=body.reason,
        )  # fmt: skip
    return {"sanction": {"id": sanction_id}}


@router.delete("/admin/sanctions/{sanction_id}")
async def revoke_sanction(sanction_id: int, reason: str | None = Query(None, max_length=500), scope: StaffScope = Depends(staff_scope)):
    async with SessionLocal() as db, db.begin():
        await sanctions.revoke(db, scope, sanction_id, reason)
    return {"revoked": True}
