"""알림함 읽기 — 최신순 키셋 커서(인덱스 notifications(recipient_id, created_at DESC)).
대상 글은 지금 다시 판정한다(readable_posts_clause) — 열 수 없게 된 글·지워진 글은 제목을 가린다(§7)."""

from sqlalchemy import Row, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.auth.viewer import Viewer
from app.core.cursor import Cursor, before, cut
from app.models import Board, Member, Notification, Post
from app.permissions import readable_posts_clause

PAGE_SIZE = 30


async def list_notifications(db: AsyncSession, viewer: Viewer, after: Cursor | None) -> tuple[list[Row], set[int], Cursor | None]:
    actor = aliased(Member)
    stmt = (
        select(
            Notification.id,
            Notification.type,
            Notification.actor_count,
            actor.display_name.label("actor_name"),
            Notification.post_id,
            Notification.comment_id,
            Notification.title_snapshot,
            Notification.created_at,
            Notification.updated_at,
            Notification.read_at,
            Board.slug.label("board_slug"),
        )
        .outerjoin(actor, actor.id == Notification.actor_id)
        .outerjoin(Post, Post.id == Notification.post_id)
        .outerjoin(Board, Board.id == Post.board_id)
        .where(Notification.recipient_id == viewer.member_id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(PAGE_SIZE + 1)
    )
    if after is not None:
        stmt = stmt.where(before(Notification.created_at, Notification.id, after))
    rows, next_cursor = cut(await db.execute(stmt), PAGE_SIZE)
    post_ids = {r.post_id for r in rows if r.post_id is not None}
    readable: set[int] = set()
    if post_ids:
        readable = set(
            (await db.execute(select(Post.id).where(Post.id.in_(post_ids), readable_posts_clause(viewer)))).scalars()
        )
    return rows, readable, next_cursor
