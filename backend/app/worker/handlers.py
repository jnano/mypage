"""outbox 처리기 — 이벤트 종류마다 하나. 멱등이어야 한다(같은 이벤트가 두 번 와도 결과가 같게)."""

import httpx
from sqlalchemy import literal_column, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.invalidation import tags_for
from app.core.outbox import enqueue_revalidate
from app.models import Board, OutboxEvent, Post, PostSearch
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
async def post_created(_db: AsyncSession, _event: OutboxEvent) -> None:
    """새 글 — 게시판 구독 알림(board.new_post)은 알림 묶음(2단계 1-3)에서 붙는다."""


@handles("post.updated")
async def post_updated(_db: AsyncSession, _event: OutboxEvent) -> None:
    """글 수정 — 지금은 할 일 없음(캐시는 Server Action 이 updateTag 로 처리)."""
