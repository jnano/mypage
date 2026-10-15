"""댓글 쓰기 — 작성·수정·삭제(소프트). 순서는 글쓰기와 같다(§3.1-4): 판정 → 멱등 키 → 요청 수 제한 → 본 트랜잭션.

본 트랜잭션에 댓글 행·post_stats.comment_count·outbox(comment.*, 알림이 받는다)·멱등 응답이 함께 들어간다.
comment_count 는 살아 있는(published) 댓글 수 — 블라인드는 세고, 지운 댓글은 뺀다.
"""

from typing import Any

from sqlalchemy import func, insert, literal_column, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.viewer import Viewer
from app.boards import spam
from app.comments import queries
from app.comments.schemas import CommentCreate, CommentUpdate
from app.core import idempotency, outbox, rate_limit
from app.core.invalidation import tags_for
from app.core.problems import Problem
from app.db.session import SessionLocal
from app.models import Board, Comment, Member, PostStat
from app.permissions import BoardRole, can, load_board_role
from app.posts import queries as post_queries
from app.posts.service import WriteResult

PUBLISHED = literal_column("'published'")


def _require_member(viewer: Viewer) -> None:
    if viewer.member_id is None:
        raise Problem(401, "login_required", "로그인이 필요합니다")


async def _load_post(db: AsyncSession, viewer: Viewer, post_id: int):
    found = await post_queries.find_post_for_view(db, post_id)
    if found is None:
        raise Problem(404, "post_not_found", "글을 찾을 수 없습니다")
    post, board = found
    return post, board, await load_board_role(db, viewer, board.id)


async def _load_comment(viewer: Viewer, comment_id: int) -> tuple[Any, Any, Board, BoardRole]:
    async with SessionLocal() as db:
        comment = await queries.find_comment(db, comment_id)
        if comment is None or comment.status != "published":
            raise Problem(404, "comment_not_found", "댓글을 찾을 수 없습니다")
        post, board, role = await _load_post(db, viewer, comment.post_id)
    return comment, post, board, role


def _invalid(field: str, message: str) -> Problem:
    return Problem(422, "validation_error", "입력값이 올바르지 않습니다", errors=[{"field": field, "message": message}])


async def create_comment(viewer: Viewer, post_id: int, body: CommentCreate, idempotency_key: str | None) -> WriteResult:
    _require_member(viewer)
    async with SessionLocal() as db:
        post, board, role = await _load_post(db, viewer, post_id)
        if not can(viewer, role, "comment.create", board, post):
            if not can(viewer, role, "post.read", board, post):
                raise Problem(404, "post_not_found", "글을 찾을 수 없습니다")
            raise Problem(403, "comment_create_forbidden", "이 글에 댓글을 쓸 수 없습니다")
        parent_id = reply_to = None
        if body.reply_to is not None:
            target = await queries.find_comment(db, body.reply_to)
            if target is None or target.post_id != post_id or target.status != "published":
                raise _invalid("reply_to", "답할 댓글이 이 글에 없습니다")
            reply_to = target.id
            parent_id = target.parent_id or target.id  # 1단: 답글의 답글은 같은 부모 아래
        if not spam.exempt(viewer, role):  # 스팸 정책: 금지어·링크 수(길이는 댓글 형식이 정한다)
            spam.check_text(await spam.policy_for(db, board), title="", text=body.content, html="", length=False)

    claim = None
    if idempotency_key is not None:
        req_hash = idempotency.request_hash(f"POST /posts/{post_id}/comments", body.model_dump())
        claimed = await idempotency.claim(f"m:{viewer.member_id}", idempotency_key, req_hash)
        if isinstance(claimed, idempotency.Replay):
            return WriteResult(claimed.status_code, claimed.body, {"Idempotency-Replayed": "true"})
        claim = claimed
    try:
        await rate_limit.hit("comment.create", f"m:{viewer.member_id}")
        async with SessionLocal() as db, db.begin():
            name = (await db.execute(select(Member.display_name).where(Member.id == viewer.member_id))).scalar_one()
            comment_id = (
                await db.execute(
                    insert(Comment)
                    .values(
                        post_id=post_id,
                        member_id=viewer.member_id,
                        author_name_snapshot=name,
                        parent_id=parent_id,
                        reply_to_comment_id=reply_to,
                        content=body.content,
                    )
                    .returning(Comment.id)
                )
            ).scalar_one()
            await db.execute(
                update(PostStat).where(PostStat.post_id == post_id).values(comment_count=PostStat.comment_count + 1)
            )
            await outbox.enqueue(
                db,
                [
                    outbox.Event(
                        "comment.created",
                        {"comment_id": comment_id, "post_id": post_id, "parent_id": parent_id, "reply_to": reply_to},
                        f"comment.created:{comment_id}",
                    )
                ],
            )
            result = WriteResult(
                201,
                {
                    "comment": {"id": comment_id, "post_id": post_id, "parent_id": parent_id},
                    "invalidate": tags_for("comment.created", post_id=post_id).as_dict(),
                },
                {"Location": f"/api/comments/{comment_id}"},
            )
            if claim is not None:
                await idempotency.complete(db, claim, result.status_code, result.body)
        return result
    except BaseException:
        if claim is not None:
            await idempotency.release(claim)
        raise


async def update_comment(viewer: Viewer, comment_id: int, body: CommentUpdate) -> WriteResult:
    _require_member(viewer)
    comment, post, board, role = await _load_comment(viewer, comment_id)
    if not can(viewer, role, "comment.update", board, post, comment=comment):
        raise Problem(403, "comment_update_forbidden", "이 댓글을 고칠 수 없습니다")
    if not spam.exempt(viewer, role):
        async with SessionLocal() as db:
            spam.check_text(await spam.policy_for(db, board), title="", text=body.content, html="", length=False)
    await rate_limit.hit("comment.update", f"m:{viewer.member_id}")
    async with SessionLocal() as db, db.begin():
        changed = (
            await db.execute(
                update(Comment)
                .where(Comment.id == comment_id, Comment.status == PUBLISHED)
                .values(content=body.content, edited_at=func.now())
                .returning(Comment.id)
            )
        ).scalar_one_or_none()
        if changed is None:
            raise Problem(404, "comment_not_found", "댓글을 찾을 수 없습니다")
    return WriteResult(
        200,
        {"comment": {"id": comment_id}, "invalidate": tags_for("comment.updated", post_id=post.id).as_dict()},
        {},
    )


async def delete_comment(viewer: Viewer, comment_id: int) -> WriteResult:
    """소프트 삭제 — 내용을 비운다. 답글이 있으면 목록에 '삭제된 댓글' 자리만 남는다."""
    _require_member(viewer)
    comment, post, board, role = await _load_comment(viewer, comment_id)
    if not can(viewer, role, "comment.delete", board, post, comment=comment):
        raise Problem(403, "comment_delete_forbidden", "이 댓글을 지울 수 없습니다")
    async with SessionLocal() as db, db.begin():
        changed = (
            await db.execute(
                update(Comment)
                .where(Comment.id == comment_id, Comment.status == PUBLISHED)
                .values(status="deleted", content="")
                .returning(Comment.id)
            )
        ).scalar_one_or_none()
        if changed is None:
            raise Problem(404, "comment_not_found", "댓글을 찾을 수 없습니다")
        await db.execute(
            update(PostStat).where(PostStat.post_id == post.id).values(comment_count=PostStat.comment_count - 1)
        )
        await outbox.enqueue(db, [outbox.Event("comment.deleted", {"comment_id": comment_id, "post_id": post.id})])
    return WriteResult(
        200,
        {"comment": {"id": comment_id}, "invalidate": tags_for("comment.deleted", post_id=post.id).as_dict()},
        {},
    )
