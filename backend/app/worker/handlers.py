"""outbox 처리기 — 이벤트 종류마다 하나. 멱등이어야 한다(같은 이벤트가 두 번 와도 결과가 같게)."""

import httpx
from sqlalchemy import literal_column, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.invalidation import tags_for
from app.core.outbox import enqueue_revalidate
from app.models import Board, Comment, OutboxEvent, Post, PostSearch
from app.notifications import send
from app.search.index import post_open
from app.worker.core import handles

# 테스트가 가짜 전송을 끼운다(httpx.MockTransport)
transport: httpx.AsyncBaseTransport | None = None


@handles("cache.revalidate")
async def revalidate(_db: AsyncSession, event: OutboxEvent) -> None:
    """Next Route Handler POST /api/revalidate — now → revalidateTag(tag, {expire: 0}), max → revalidateTag(tag, 'max')."""
    async with httpx.AsyncClient(transport=transport, timeout=10) as client:
        res = await client.post(
            settings.next_revalidate_url,
            json={"now": event.payload.get("now", []), "max": event.payload.get("max", [])},
            headers={"X-Internal-Secret": settings.internal_api_secret},
        )
    res.raise_for_status()


@handles("post.publish_scheduled")
async def publish_scheduled(db: AsyncSession, event: OutboxEvent) -> None:
    """예약 발행 — available_at 이 예정 시각. 이미 발행됐거나 예약이 취소·변경됐으면 아무것도 하지 않는다."""
    post_id = int(event.payload["post_id"])
    row = (
        await db.execute(
            update(Post)
            .where(
                Post.id == post_id,
                Post.status == literal_column("'scheduled'"),
                Post.published_at <= event.available_at,
            )
            .values(status="published")
            .returning(Post.id, Post.board_id, Post.is_secret, Post.is_blinded, Post.min_view_level, Post.published_at)
        )
    ).one_or_none()
    if row is None:
        return
    await db.execute(
        update(PostSearch)
        .where(PostSearch.post_id == post_id)
        .values(post_open=post_open("published", row.is_secret, row.is_blinded, row.min_view_level))
    )
    slug = (await db.execute(select(Board.slug).where(Board.id == row.board_id))).scalar_one()
    await enqueue_revalidate(db, [tags_for("post.status_changed", post_id=post_id, board_slug=slug)])


@handles("post.created")
async def post_created(db: AsyncSession, event: OutboxEvent) -> None:
    """새 글 — 공개 글이면 게시판 구독자에게(board.new_post), 승인 대기면 담당자에게(admin.guest_pending)."""
    post = (
        await db.execute(
            select(  # post-clause: exempt — 알림 받는 사람 계산(열람 조건은 send.notify_board_subscribers 의 SQL)
                Post.id, Post.board_id, Post.member_id, Post.title, Post.status, Post.is_secret, Post.min_view_level
            ).where(Post.id == int(event.payload["post_id"]))
        )
    ).one_or_none()
    if post is None:
        return
    board = (await db.execute(select(Board).where(Board.id == post.board_id))).scalar_one()
    if post.status == "published":
        await send.notify_board_subscribers(
            db, board=board, post_id=post.id, author_id=post.member_id, title=post.title,
            is_secret=post.is_secret, min_view_level=post.min_view_level,
        )  # fmt: skip
    elif post.status == "pending":
        await send.notify_moderators(
            db, board_id=board.id, type_name="admin.guest_pending", actor_id=post.member_id,
            post_id=post.id, title=post.title, dedupe_key=f"post.created:{post.id}:pending",
        )  # fmt: skip


@handles("post.updated")
async def post_updated(_db: AsyncSession, _event: OutboxEvent) -> None:
    """글 수정 — 할 일 없음(캐시는 Server Action 이 updateTag 로 처리)."""


@handles("comment.created")
async def comment_created(db: AsyncSession, event: OutboxEvent) -> None:
    """내 글에 댓글(comment.on_my_post), 내 댓글에 답글(comment.reply). 같은 사람이 둘 다라면 답글 알림 하나만."""
    comment = (
        await db.execute(
            select(Comment.id, Comment.post_id, Comment.member_id, Comment.reply_to_comment_id, Comment.status).where(
                Comment.id == int(event.payload["comment_id"])
            )
        )
    ).one_or_none()
    if comment is None or comment.status != "published":
        return
    post = (
        await db.execute(
            select(Post.id, Post.member_id, Post.is_guest, Post.title).where(Post.id == comment.post_id)  # post-clause: exempt — 알림 받는 사람(글쓴이) 찾기
        )
    ).one()
    replied = set()
    if comment.reply_to_comment_id is not None:
        target = (
            await db.execute(select(Comment.member_id).where(Comment.id == comment.reply_to_comment_id))
        ).scalar_one_or_none()
        if target is not None:
            replied.add(target)
            await send.notify(
                db, recipients=[target], type_name="comment.reply", actor_id=comment.member_id, post_id=post.id,
                comment_id=comment.id, title=post.title, group_key=f"comment.reply:comment:{comment.reply_to_comment_id}",
                dedupe_key=f"comment.created:{comment.id}:reply",
            )  # fmt: skip
    if not post.is_guest and post.member_id is not None and post.member_id not in replied:
        await send.notify(
            db, recipients=[post.member_id], type_name="comment.on_my_post", actor_id=comment.member_id,
            post_id=post.id, comment_id=comment.id, title=post.title, group_key=f"comment.on_my_post:post:{post.id}",
            dedupe_key=f"comment.created:{comment.id}:on_my_post",
        )  # fmt: skip


@handles("comment.deleted")
async def comment_deleted(_db: AsyncSession, _event: OutboxEvent) -> None:
    """댓글 삭제 — 이미 보낸 알림은 그대로 둔다(알림함이 지워진 댓글을 다시 확인하지는 않는다)."""
