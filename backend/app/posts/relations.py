"""관련 글 편집 — 설계도 §6.2. 원본 글의 담당자·운영자와 회원 작성자(post.relate)가 한 글에 최대 10개까지 붙인다.

개수는 원본 글 행을 FOR NO KEY UPDATE 로 잠그고 센 뒤 넣는다 — 같은 원본의 동시 추가가 10을 넘지 않는다.
관계는 한쪽 방향이라 무효화는 원본 글(post:{원본}) 하나다(§3.4 post.relations_changed).
"""

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.logs import LogEntry, record
from app.auth.viewer import Viewer
from app.core import rate_limit
from app.core.invalidation import tags_for
from app.core.problems import Problem
from app.db.session import SessionLocal
from app.models import Board, Post, PostRelation
from app.permissions import can, load_board_role, readable_posts_clause
from app.posts.queries import RELATED_LIMIT


def _not_found() -> Problem:
    return Problem(404, "post_not_found", "글을 찾을 수 없습니다")


def _invalid(message: str) -> Problem:
    return Problem(422, "validation_error", "입력값이 올바르지 않습니다", errors=[{"field": "target_id", "message": message}])


async def _authorize(db: AsyncSession, viewer: Viewer, post_id: int, *, lock: bool) -> tuple[Board, bool]:
    """(게시판, 남의 글을 담당자로서 바꾸는가). 읽을 수 없으면 404, 편집 권한이 없으면 403"""
    stmt = select(Post.id, Post.board_id, Post.member_id, Post.is_guest, Post.status, Post.is_secret, Post.is_blinded, Post.min_view_level, Board).join(  # post-clause: exempt — 한 건, 아래 can() 판정
        Board, Board.id == Post.board_id
    ).where(Post.id == post_id)
    if lock:
        stmt = stmt.with_for_update(key_share=True, of=Post)  # FOR NO KEY UPDATE
    row = (await db.execute(stmt)).one_or_none()
    if row is None:
        raise _not_found()
    role = await load_board_role(db, viewer, row.Board.id)
    if not can(viewer, role, "post.read", row.Board, row):
        raise _not_found()
    if not can(viewer, role, "post.relate", row.Board, row):
        raise Problem(403, "relations_forbidden", "이 글의 관련 글을 바꿀 수 없습니다")
    by_staff = row.member_id != viewer.member_id
    return row.Board, by_staff


async def list_for(db: AsyncSession, viewer: Viewer, post_id: int) -> list[dict]:
    """편집하는 사람 기준 — 읽을 수 없게 된 대상은 제목 없이 readable=false(지울 수 있게 남긴다)"""
    rows = list(
        await db.execute(
            select(PostRelation.target_post_id.label("id"), Post.title, Board.slug.label("board_slug"))  # post-clause: exempt — 제목은 아래 readable 로 가린다
            .join(Post, Post.id == PostRelation.target_post_id)
            .join(Board, Board.id == Post.board_id)
            .where(PostRelation.source_post_id == post_id)
            .order_by(PostRelation.created_at, PostRelation.target_post_id)
        )
    )
    ids = {r.id for r in rows}
    readable = set((await db.execute(select(Post.id).where(Post.id.in_(ids), readable_posts_clause(viewer)))).scalars()) if ids else set()
    return [
        {"id": r.id, "title": r.title if r.id in readable else None, "board_slug": r.board_slug if r.id in readable else None, "readable": r.id in readable}
        for r in rows
    ]


def _require_member(viewer: Viewer) -> None:
    if viewer.member_id is None:
        raise Problem(401, "login_required", "로그인이 필요합니다")


async def get(viewer: Viewer, post_id: int) -> dict:
    _require_member(viewer)
    async with SessionLocal() as db:
        await _authorize(db, viewer, post_id, lock=False)
        return {"items": await list_for(db, viewer, post_id)}


async def add(viewer: Viewer, post_id: int, target_id: int) -> dict:
    _require_member(viewer)
    if target_id == post_id:
        raise _invalid("자기 글은 관련 글로 붙일 수 없습니다")
    await rate_limit.hit("post.update", f"m:{viewer.member_id}")
    async with SessionLocal() as db, db.begin():
        board, by_staff = await _authorize(db, viewer, post_id, lock=True)
        target_ok = (
            await db.execute(select(Post.id).where(Post.id == target_id, readable_posts_clause(viewer)))
        ).scalar_one_or_none()
        if target_ok is None:  # 없는 글·읽을 수 없는 글을 가르지 않는다
            raise _invalid("붙일 수 있는 글이 아닙니다")
        exists_ = (
            await db.execute(select(PostRelation.target_post_id).where(PostRelation.source_post_id == post_id, PostRelation.target_post_id == target_id))
        ).scalar_one_or_none()
        if exists_ is None:
            count = (await db.execute(select(func.count()).where(PostRelation.source_post_id == post_id))).scalar_one()
            if count >= RELATED_LIMIT:
                raise Problem(409, "relations_full", f"관련 글은 {RELATED_LIMIT}개까지입니다")
            await db.execute(
                insert(PostRelation).values(source_post_id=post_id, target_post_id=target_id, created_by=viewer.member_id).on_conflict_do_nothing()
            )
            if by_staff:
                await record(db, viewer, [LogEntry("post.relate", "post", post_id, board_id=board.id, after={"added": target_id})])
        items = await list_for(db, viewer, post_id)
    return {"items": items, "invalidate": tags_for("post.relations_changed", post_id=post_id).as_dict()}


async def remove(viewer: Viewer, post_id: int, target_id: int) -> dict:
    _require_member(viewer)
    await rate_limit.hit("post.update", f"m:{viewer.member_id}")
    async with SessionLocal() as db, db.begin():
        board, by_staff = await _authorize(db, viewer, post_id, lock=True)
        gone = (
            await db.execute(
                delete(PostRelation).where(PostRelation.source_post_id == post_id, PostRelation.target_post_id == target_id).returning(PostRelation.target_post_id)
            )
        ).scalar_one_or_none()
        if gone is not None and by_staff:
            await record(db, viewer, [LogEntry("post.relate", "post", post_id, board_id=board.id, before={"removed": target_id})])
        items = await list_for(db, viewer, post_id)
    return {"items": items, "invalidate": tags_for("post.relations_changed", post_id=post_id).as_dict()}

