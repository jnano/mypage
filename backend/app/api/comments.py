"""댓글 API — 설계도 §6. 글은 전역 id, 댓글도 전역 id."""

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.viewer import Viewer, get_viewer
from app.comments import present, queries, service
from app.comments.schemas import CommentCreate, CommentUpdate
from app.core.problems import Problem
from app.db.session import get_db
from app.permissions import can, load_board_role
from app.posts import queries as post_queries

router = APIRouter()


@router.get("/posts/{post_id}/comments")
async def list_comments(
    post_id: int,
    cursor: str | None = Query(None, max_length=40),
    viewer: Viewer = Depends(get_viewer),
    db: AsyncSession = Depends(get_db),
):
    """첫 쪽은 글 묶음 응답(/posts/{id}/page)에 들어 있다. 여기는 '더 보기'."""
    found = await post_queries.find_post_for_view(db, post_id)
    if found is None:
        raise Problem(404, "post_not_found", "글을 찾을 수 없습니다")
    post, board = found
    role = await load_board_role(db, viewer, board.id)
    if not can(viewer, role, "post.read", board, post):
        raise Problem(404, "post_not_found", "글을 찾을 수 없습니다")
    try:
        after = queries.Cursor.decode(cursor) if cursor else None
    except ValueError:
        raise Problem(422, "validation_error", "cursor 가 올바르지 않습니다") from None
    rows, next_cursor = await queries.list_comments(db, post_id, after)
    body = present.comments_page(viewer, role, rows, next_cursor) | {"cache": {"tags": [f"post:{post_id}"]}}
    return body


@router.post("/posts/{post_id}/comments", status_code=201)
async def create_comment(
    post_id: int,
    body: CommentCreate,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    viewer: Viewer = Depends(get_viewer),
):
    result = await service.create_comment(viewer, post_id, body, idempotency_key)
    return JSONResponse(result.body, status_code=result.status_code, headers=result.headers)


@router.patch("/comments/{comment_id}")
async def update_comment(comment_id: int, body: CommentUpdate, viewer: Viewer = Depends(get_viewer)):
    result = await service.update_comment(viewer, comment_id, body)
    return JSONResponse(result.body, status_code=result.status_code)


@router.delete("/comments/{comment_id}")
async def delete_comment(comment_id: int, viewer: Viewer = Depends(get_viewer)):
    result = await service.delete_comment(viewer, comment_id)
    return JSONResponse(result.body, status_code=result.status_code)
