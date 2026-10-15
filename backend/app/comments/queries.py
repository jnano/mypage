"""댓글 읽기 — 스레드 순서(원댓글 → 그 답글들), 키셋 커서. 글 열람 판정은 호출부(can(post.read))."""

from dataclasses import dataclass

from sqlalchemy import Row, Select, and_, exists, func, literal_column, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import Comment

PAGE_SIZE = 100
PUBLISHED = literal_column("'published'")


def thread_key():
    """원댓글은 자기 id, 답글은 부모 id — 같은 스레드가 붙어 나온다(id 는 시간 순)."""
    return func.coalesce(Comment.parent_id, Comment.id)


@dataclass(frozen=True)
class Cursor:
    thread: int
    id: int

    def encode(self) -> str:
        return f"{self.thread}.{self.id}"

    @staticmethod
    def decode(raw: str) -> "Cursor":
        thread, _, cid = raw.partition(".")
        if not (thread.isdigit() and cid.isdigit()):
            raise ValueError("cursor")
        return Cursor(int(thread), int(cid))


def comments_statement(post_id: int, after: Cursor | None, limit: int = PAGE_SIZE) -> Select:
    reply = aliased(Comment)
    visible = or_(
        Comment.status == PUBLISHED,
        # 지운 원댓글은 살아 있는 답글이 있을 때만 자리를 남긴다
        and_(
            Comment.parent_id.is_(None),
            # 같은 글 조건으로 ix_comments_post 를 탄다 — parent_id 인덱스가 없어 이 조건이 없으면 지운 원댓글마다
            # 댓글 표 전체를 훑었다(3단계 측정: 댓글 27만 건·지운 원댓글 20개에 435ms → 1.5ms)
            exists().where(reply.post_id == Comment.post_id, reply.parent_id == Comment.id, reply.status == PUBLISHED).correlate_except(reply),
        ),
    )
    target = aliased(Comment)
    stmt = (
        select(
            Comment.id,
            Comment.parent_id,
            Comment.reply_to_comment_id,
            target.author_name_snapshot.label("reply_to_name"),
            Comment.member_id,
            Comment.author_name_snapshot,
            Comment.content,
            Comment.status,
            Comment.is_blinded,
            Comment.edited_at,
            Comment.created_at,
            thread_key().label("thread"),
        )
        .outerjoin(target, target.id == Comment.reply_to_comment_id)
        .where(Comment.post_id == post_id, visible)
        .order_by(thread_key(), Comment.id)
        .limit(limit + 1)
    )
    if after is not None:
        stmt = stmt.where(tuple_(thread_key(), Comment.id) > tuple_(after.thread, after.id))
    return stmt


async def list_comments(db: AsyncSession, post_id: int, after: Cursor | None = None) -> tuple[list[Row], Cursor | None]:
    rows = list(await db.execute(comments_statement(post_id, after)))
    if len(rows) > PAGE_SIZE:
        rows = rows[:PAGE_SIZE]
        return rows, Cursor(rows[-1].thread, rows[-1].id)
    return rows, None


async def find_comment(db: AsyncSession, comment_id: int) -> Row | None:
    return (
        await db.execute(
            select(Comment.id, Comment.post_id, Comment.parent_id, Comment.member_id, Comment.status).where(
                Comment.id == comment_id
            )
        )
    ).one_or_none()
