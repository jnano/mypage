"""내 목록 — 설계도 §6.2. 내 글·내 댓글·스크랩, 최신순 키셋 커서(app.core.cursor).

본인 것만 읽는다(호출부가 회원 id 를 넘긴다 — 경로에 id 가 없다). 글 행을 목록마다 다시 읽지 않고,
'지금 읽을 수 있는가'는 목록의 글 id 를 IN 으로 묶어 readable_posts_clause 로 한 번에 판정한다(알림함 §7 과 같은 방식).
"""

from sqlalchemy import Row, func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.viewer import Viewer
from app.core.cursor import Cursor, before, cut
from app.models import Board, Comment, Post, PostScrap, PostStat
from app.permissions import own_posts_openable_clause, readable_posts_clause

PAGE_SIZE = 30
EXCERPT = 100

TRASHED = literal_column("'trashed'")
PUBLISHED = literal_column("'published'")


async def readable_ids(db: AsyncSession, viewer: Viewer, post_ids: set[int]) -> set[int]:
    if not post_ids:
        return set()
    stmt = select(Post.id).where(Post.id.in_(post_ids), readable_posts_clause(viewer))
    return set((await db.execute(stmt)).scalars())


async def my_posts(db: AsyncSession, viewer: Viewer, after: Cursor | None) -> tuple[list[Row], set[int], Cursor | None]:
    """휴지통 글은 뺀다. 내 글은 상태·제목과 함께 늘 보이지만, 링크는 지금 열 수 있을 때만(돌려주는 집합) —
    작성자도 게시판 조건(사용 중지·회원 전용 전환·등급)을 통과해야 읽는다(§5.3, 검토 v4.0.9 N-1)"""
    stmt = (
        select(  # post-clause: exempt — 본인 글만(member_id), 상태는 배지로 보인다
            Post.id,
            Post.title,
            Post.status,
            Post.is_secret,
            Post.is_blinded,
            Post.created_at,
            Post.published_at,
            Board.slug.label("board_slug"),
            Board.name.label("board_name"),
            PostStat.comment_count,
            PostStat.like_count,
        )
        .join(Board, Board.id == Post.board_id)
        .outerjoin(PostStat, PostStat.post_id == Post.id)
        .where(Post.member_id == viewer.member_id, Post.status != TRASHED)
        .order_by(Post.created_at.desc(), Post.id.desc())
        .limit(PAGE_SIZE + 1)
    )
    if after is not None:
        stmt = stmt.where(before(Post.created_at, Post.id, after))
    rows, next_cursor = cut(await db.execute(stmt), PAGE_SIZE)
    return rows, await openable_ids(db, viewer, rows), next_cursor


async def openable_ids(db: AsyncSession, viewer: Viewer, rows: list[Row]) -> set[int]:
    """내 글 가운데 지금 열 수 있는 글 — 쿼리 한 번(own_posts_openable_clause)"""
    if not rows:
        return set()
    stmt = select(Post.id).where(Post.id.in_({r.id for r in rows}), own_posts_openable_clause(viewer))
    return set((await db.execute(stmt)).scalars())


async def my_comments(db: AsyncSession, viewer: Viewer, after: Cursor | None) -> tuple[list[Row], set[int], Cursor | None]:
    """지운 댓글은 뺀다. 글 제목은 지금 읽을 수 있을 때만(돌려주는 집합)"""
    stmt = (
        select(
            Comment.id,
            func.left(Comment.content, EXCERPT).label("excerpt"),
            Comment.is_blinded,
            Comment.created_at,
            Comment.post_id,
            Post.title.label("post_title"),
            Board.slug.label("board_slug"),
        )
        .join(Post, Post.id == Comment.post_id)
        .join(Board, Board.id == Post.board_id)
        .where(Comment.member_id == viewer.member_id, Comment.status == PUBLISHED)  # 글 제목은 readable_ids 로 가린다
        .order_by(Comment.created_at.desc(), Comment.id.desc())
        .limit(PAGE_SIZE + 1)
    )
    if after is not None:
        stmt = stmt.where(before(Comment.created_at, Comment.id, after))
    rows, next_cursor = cut(await db.execute(stmt), PAGE_SIZE)
    return rows, await readable_ids(db, viewer, {r.post_id for r in rows}), next_cursor


async def my_scraps(db: AsyncSession, viewer: Viewer, after: Cursor | None) -> tuple[list[Row], set[int], Cursor | None]:
    """스크랩한 때 최신순. 지금 읽을 수 없는 글은 제목을 가린다(지우기는 남긴다)"""
    stmt = (
        select(  # post-clause: exempt — 제목은 readable_ids 로 가린다
            PostScrap.post_id,
            PostScrap.created_at,
            Post.title,
            Board.slug.label("board_slug"),
            Board.name.label("board_name"),
        )
        .join(Post, Post.id == PostScrap.post_id)
        .join(Board, Board.id == Post.board_id)
        .where(PostScrap.member_id == viewer.member_id)
        .order_by(PostScrap.created_at.desc(), PostScrap.post_id.desc())
        .limit(PAGE_SIZE + 1)
    )
    if after is not None:
        stmt = stmt.where(before(PostScrap.created_at, PostScrap.post_id, after))
    rows, next_cursor = cut(await db.execute(stmt), PAGE_SIZE, key="post_id")
    return rows, await readable_ids(db, viewer, {r.post_id for r in rows}), next_cursor
