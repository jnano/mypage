"""글 화면 묶음 응답·수정 — 설계도 §3.6, §6. 글은 전역 id 로 찾는다(게시판을 옮겨도 주소 유지)."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse
from sqlalchemy import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.viewer import Viewer, get_viewer
from app.comments import present as comment_present
from app.comments import queries as comment_queries
from app.core.problems import Problem
from app.db.session import get_db
from app.models import Board
from app.permissions import BoardRole, can, load_board_role
from app.posts import present, queries, service
from app.posts.schemas import PostUpdate

router = APIRouter()


def _read_denied(viewer: Viewer, role: BoardRole, board: Board, post: Row) -> Problem:
    """열람 거부 사유. 공개 상태가 아닌 글·사용 중지 게시판은 존재를 드러내지 않는다(404)."""
    not_found = Problem(404, "post_not_found", "글을 찾을 수 없습니다")
    if post.status != "published" or not board.is_active:
        return not_found
    if not can(viewer, role, "board.list", board):
        return Problem(403, "board_forbidden", "이 게시판을 볼 권한이 없습니다")
    if post.is_blinded:
        return Problem(403, "post_blinded", "운영 정책에 따라 가려진 글입니다")
    if post.is_secret:
        return Problem(403, "post_secret", "비밀글입니다")
    return Problem(403, "post_level", "이 글을 볼 수 있는 등급이 아닙니다")


@router.get("/posts/{post_id}/page")
async def post_page(
    post_id: int,
    viewer: Viewer = Depends(get_viewer),
    db: AsyncSession = Depends(get_db),
):
    found = await queries.find_post_for_view(db, post_id)
    if found is None:
        if await queries.is_tombstoned(db, post_id):
            raise Problem(410, "post_gone", "삭제된 글입니다")
        raise Problem(404, "post_not_found", "글을 찾을 수 없습니다")
    post, board = found
    role = await load_board_role(db, viewer, board.id)
    if not can(viewer, role, "post.read", board, post):
        raise _read_denied(viewer, role, board, post)

    neighbors: dict = {"prev": None, "next": None}
    if post.status == "published" and post.published_at is not None:
        found_n = await queries.find_neighbors(db, viewer, board.id, post.published_at, post.id)
        neighbors = {k: present.neighbor(viewer, role, v) for k, v in found_n.items()}
    related = await queries.find_related(db, viewer, post.id)
    attachments = await queries.list_attachments(db, post.id)
    comment_rows, next_cursor = await comment_queries.list_comments(db, post.id)
    now = datetime.now(UTC)
    return {
        "board": present.board_summary(board),
        "post": present.post_view(post, board, now),
        "neighbors": neighbors,
        "related": [{"id": r.id, "title": r.title, "board_slug": r.board_slug} for r in related],
        "attachments": [present.attachment_item(a) for a in attachments],
        # 첫 쪽 댓글을 함께 — 따로 부르면 화면당 FastAPI 호출 예산(로그인 ≤ 3)을 넘는다(§3.6)
        "comments": comment_present.comments_page(viewer, role, comment_rows, next_cursor),
        "cache": {"tags": [f"post:{post.id}", f"board:{board.slug}"]},
    }


@router.get("/posts/{post_id}")
async def get_post_for_edit(
    post_id: int,
    viewer: Viewer = Depends(get_viewer),
    db: AsyncSession = Depends(get_db),
):
    """수정 화면용 — 쓴 형식의 원문(마크다운) 또는 정본(리치)과 version(ETag)."""
    found = await queries.find_post_for_edit(db, post_id)
    if found is None:
        raise Problem(404, "post_not_found", "글을 찾을 수 없습니다")
    post, board = found
    role = await load_board_role(db, viewer, board.id)
    if not can(viewer, role, "post.update", board, post):
        raise Problem(403, "post_update_forbidden", "이 글을 수정할 권한이 없습니다")
    files = await queries.list_attachments(db, post.id, include_inline=True)
    body = {
        "id": post.id,
        "board_slug": board.slug,
        "title": post.title,
        "content_format": post.content_format,
        "content": post.content_source if post.content_format == "markdown" else post.content_html,
        "category_ids": list(post.category_ids or []),
        "is_secret": post.is_secret,
        "status": post.status,
        "version": post.version,
        "attachments": [present.attachment_item(a) for a in files],
    }
    return JSONResponse(body, headers={"ETag": f'"{post.version}"', "Cache-Control": "no-store"})


@router.patch("/posts/{post_id}")
async def update_post(
    post_id: int,
    body: PostUpdate,
    if_match: str | None = Header(None, alias="If-Match"),
    reason: str | None = Query(None, max_length=500, description="관리 칸 조치의 사유(운영 기록)"),
    viewer: Viewer = Depends(get_viewer),
):
    result = await service.update_post(viewer, post_id, body, if_match, reason)
    return JSONResponse(result.body, status_code=result.status_code, headers=result.headers)
