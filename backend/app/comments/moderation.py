"""댓글 관리 조치 — 설계도 §14.2 '댓글'(통합 목록·일괄 가림·삭제). 신고 처리도 같은 함수를 쓴다.

담당자(또는 운영자)만. 하나라도 범위 밖이면 아무것도 바꾸지 않고 403 + id 목록(글 일괄 조치와 같은 규칙).
"""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.logs import LogEntry, record
from app.auth.viewer import Viewer
from app.core import outbox
from app.core.invalidation import tags_for
from app.core.problems import Problem
from app.models import Board, Comment, Post, PostStat
from app.notifications.send import notify
from app.permissions import load_board_roles


async def load_comments(db: AsyncSession, viewer: Viewer, ids: Sequence[int]) -> list[Any]:
    """대상 댓글(+ 글·게시판). 없거나 지운 댓글은 404, 범위 밖이면 403 + id 목록."""
    if viewer.member_id is None:
        raise Problem(401, "login_required", "로그인이 필요합니다")
    rows = (
        await db.execute(
            select(Comment.id, Comment.post_id, Comment.member_id, Comment.status, Comment.is_blinded, Comment.blind_source, Comment.content, Post.title, Post.board_id, Board.slug)  # post-clause: exempt — 관리 조치 대상(판정은 아래 담당자 확인)
            .join(Post, Post.id == Comment.post_id)
            .join(Board, Board.id == Post.board_id)
            .where(Comment.id.in_(list(ids)))
            .with_for_update(of=Comment)
        )
    ).all()
    found = {r.id for r in rows if r.status == "published"}
    if missing := [i for i in ids if i not in found]:
        raise Problem(404, "comment_not_found", "댓글을 찾을 수 없습니다", detail=f"ids={missing}")
    roles = await load_board_roles(db, viewer, {r.board_id for r in rows})
    if denied := [r.id for r in rows if not (viewer.is_admin or roles[r.board_id].is_moderator)]:
        raise Problem(403, "bulk_forbidden", "권한이 없는 댓글이 있습니다", detail=f"ids={denied}")
    return rows


async def apply(db: AsyncSession, viewer: Viewer, action: str, rows: list[Any], reason: str | None, *, source: str = "manual") -> dict[str, list[str]]:
    """가림·풀기·삭제(소프트). 응답 무효화 태그를 돌려준다."""
    logs: list[LogEntry] = []
    now: list[str] = []
    for r in rows:
        if action in ("blind", "unblind"):
            on = action == "blind"
            if r.is_blinded == on:
                continue
            await db.execute(update(Comment).where(Comment.id == r.id).values(is_blinded=on, blind_source=source if on else None, updated_at=func.now()))
            if on and r.member_id:
                await notify(
                    db, recipients=[r.member_id], type_name="moderation.blinded", actor_id=viewer.member_id, post_id=r.post_id,
                    comment_id=r.id, title=r.title, group_key=f"moderation:comment:{r.id}", dedupe_key=f"moderation.blinded:comment:{r.id}",
                )  # fmt: skip
            event = "comment.updated"
        elif action == "delete":
            await db.execute(update(Comment).where(Comment.id == r.id).values(status="deleted", content="", updated_at=func.now()))
            await db.execute(update(PostStat).where(PostStat.post_id == r.post_id).values(comment_count=PostStat.comment_count - 1))
            await outbox.enqueue(db, [outbox.Event("comment.deleted", {"comment_id": r.id, "post_id": r.post_id})])
            event = "comment.deleted"
        else:
            raise Problem(422, "validation_error", "알 수 없는 조치입니다")
        # 본문 앞부분은 개인 값 — 가림 작업이 지운다(§14.4)
        logs.append(
            LogEntry(f"comment.{action}", "comment", r.id, board_id=r.board_id, before={"author_id": r.member_id, "excerpt": r.content[:80], "is_blinded": r.is_blinded}, after={"action": action}, reason=reason)
        )
        now += [t for t in tags_for(event, post_id=r.post_id).now if t not in now]
    await record(db, viewer, logs)
    return {"now": now, "max": []}
