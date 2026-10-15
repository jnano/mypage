"""글 읽기 쿼리 — 용도별 칸만 읽는다(§2.2 P3). 글 조회는 모두 판정 절을 거친다(§5.2, CI 검사).

고정 조건은 SQL 리터럴(§2.2 P4) — 목록의 is_pinned = false 는 부분 인덱스 ix_posts_board_list 의 조건과 같은 모양.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Row, and_, exists, func, literal_column, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.viewer import Viewer
from app.models import (
    Attachment,
    Board,
    BoardCategory,
    BoardSlugHistory,
    Post,
    PostCategory,
    PostRelation,
    PostStat,
    PostTombstone,
)
from app.permissions import (
    BoardRole,
    listable_posts_clause,
    readable_posts_clause,
    unmasked_posts_clause,
)

MAX_PAGE = 500
PINNED_LIMIT = 20
RELATED_LIMIT = 10
FALSE = literal_column("false")
TRUE = literal_column("true")


def _category_ids():
    return func.array(
        select(PostCategory.category_id)
        .where(PostCategory.post_id == Post.id)
        .order_by(PostCategory.category_id)
        .scalar_subquery()
    ).label("category_ids")


# 목록 한 줄에 필요한 칸
LIST_COLUMNS = (
    Post.id,
    Post.title,
    Post.title_bold,
    Post.title_color,
    Post.member_id,
    Post.is_guest,
    Post.author_name_snapshot,
    Post.posted_as,
    Post.published_at,
    Post.content_updated_at,
    Post.is_secret,
    Post.is_blinded,
    Post.min_view_level,
    Post.expires_at,
    Post.is_pinned,
    PostStat.view_count,
    PostStat.like_count,
    PostStat.comment_count,
)


@dataclass(frozen=True)
class ListResult:
    pinned: list[Row]
    rows: list[Row]
    total: int
    total_capped: bool


async def find_board(db: AsyncSession, slug: str) -> Board | None:
    return (await db.execute(select(Board).where(Board.slug == slug))).scalar_one_or_none()


async def find_moved_slug(db: AsyncSession, old_slug: str) -> str | None:
    """옛 주소 → 지금 slug(§10, 308 용)."""
    return (
        await db.execute(
            select(Board.slug)
            .join(BoardSlugHistory, BoardSlugHistory.board_id == Board.id)
            .where(BoardSlugHistory.old_slug == old_slug)
        )
    ).scalar_one_or_none()


async def list_categories(db: AsyncSession, board_id: int) -> list[Row]:
    return list(
        await db.execute(
            select(BoardCategory.id, BoardCategory.name)
            .where(BoardCategory.board_id == board_id, BoardCategory.is_active.is_(TRUE))
            .order_by(BoardCategory.sort_order, BoardCategory.id)
        )
    )


async def list_board_posts(
    db: AsyncSession,
    viewer: Viewer,
    role: BoardRole,
    board: Board,
    *,
    page: int,
    per_page: int,
    category_id: int | None = None,
    archived: bool = False,
) -> ListResult:
    """게시판 목록 — 고정 글 띠 + 일반 목록 + 개수(상한까지만 센다, §15.2)."""
    common = [Post.board_id == board.id]
    if board.hidden_post_listing == "hide":
        common.append(unmasked_posts_clause(viewer, role))

    conds = [*common, listable_posts_clause(viewer, expired=archived)]
    if not archived:
        conds.append(Post.is_pinned == FALSE)
    if category_id is not None:
        conds.append(
            exists().where(PostCategory.post_id == Post.id, PostCategory.category_id == category_id)
        )
    order = (
        (Post.expires_at.desc(), Post.id.desc())
        if archived
        else (Post.published_at.desc(), Post.id.desc())
    )
    rows = list(
        await db.execute(
            select(*LIST_COLUMNS, _category_ids())
            .outerjoin(PostStat, PostStat.post_id == Post.id)
            .where(*conds)
            .order_by(*order)
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
    )

    cap = MAX_PAGE * per_page
    counted = (
        await db.execute(
            select(func.count()).select_from(
                select(Post.id).where(*conds).limit(cap + 1).subquery()
            )
        )
    ).scalar_one()

    pinned: list[Row] = []
    if not archived:
        pinned = list(
            await db.execute(
                select(*LIST_COLUMNS, _category_ids())
                .outerjoin(PostStat, PostStat.post_id == Post.id)
                .where(*common, listable_posts_clause(viewer), Post.is_pinned == TRUE)
                .order_by(Post.pin_order.asc().nulls_last(), Post.published_at.desc())
                .limit(PINNED_LIMIT)
            )
        )
    return ListResult(pinned, rows, min(counted, cap), counted > cap)


# 글 보기에 필요한 칸(정본·원문은 읽지 않는다)
VIEW_COLUMNS = (
    Post.id,
    Post.board_id,
    Post.member_id,
    Post.is_guest,
    Post.author_name_snapshot,
    Post.posted_as,
    Post.title,
    Post.title_bold,
    Post.title_color,
    Post.content_format,
    Post.content_rendered,
    Post.status,
    Post.published_at,
    Post.expires_at,
    Post.content_updated_at,
    Post.is_pinned,
    Post.is_secret,
    Post.is_blinded,
    Post.min_view_level,
    Post.version,
    PostStat.view_count,
    PostStat.like_count,
    PostStat.comment_count,
    PostStat.scrap_count,
    PostStat.share_count,
)


async def find_post_for_view(db: AsyncSession, post_id: int) -> tuple[Row, Board] | None:
    """판정 전 한 건 조회 — 권한은 호출부가 can(post.read) 로 판정한다."""
    row = (
        await db.execute(
            select(*VIEW_COLUMNS, _category_ids(), Board)  # post-clause: exempt — 한 건, 호출부가 can() 판정
            .join(Board, Board.id == Post.board_id)
            .outerjoin(PostStat, PostStat.post_id == Post.id)
            .where(Post.id == post_id)
        )
    ).one_or_none()
    if row is None:
        return None
    return row, row.Board


async def is_tombstoned(db: AsyncSession, post_id: int) -> bool:
    return (
        await db.execute(select(exists().where(PostTombstone.post_id == post_id)))
    ).scalar_one()


async def find_neighbors(
    db: AsyncSession, viewer: Viewer, board_id: int, published_at: datetime, post_id: int
) -> dict[str, Row | None]:
    """이전·다음 글 — 목록 인덱스를 키셋으로 재사용(§4.7). 쿼리 한 번."""
    base = (
        Post.board_id == board_id,
        listable_posts_clause(viewer),
        Post.is_pinned == FALSE,
    )
    older = (
        select(literal_column("'prev'").label("dir"), Post.id, Post.title, Post.is_secret, Post.is_blinded)
        .where(
            *base,
            or_(
                Post.published_at < published_at,
                and_(Post.published_at == published_at, Post.id < post_id),
            ),
        )
        .order_by(Post.published_at.desc(), Post.id.desc())
        .limit(1)
    )
    newer = (
        select(literal_column("'next'").label("dir"), Post.id, Post.title, Post.is_secret, Post.is_blinded)
        .where(
            *base,
            or_(
                Post.published_at > published_at,
                and_(Post.published_at == published_at, Post.id > post_id),
            ),
        )
        .order_by(Post.published_at.asc(), Post.id.asc())
        .limit(1)
    )
    found = {row.dir: row for row in await db.execute(union_all(older, newer))}
    return {"prev": found.get("prev"), "next": found.get("next")}


async def find_related(db: AsyncSession, viewer: Viewer, post_id: int) -> list[Row]:
    return list(
        await db.execute(
            select(Post.id, Post.title, Board.slug.label("board_slug"))
            .join(PostRelation, PostRelation.target_post_id == Post.id)
            .join(Board, Board.id == Post.board_id)
            .where(PostRelation.source_post_id == post_id, readable_posts_clause(viewer))
            .order_by(PostRelation.created_at)
            .limit(RELATED_LIMIT)
        )
    )


async def list_attachments(db: AsyncSession, post_id: int) -> list[Row]:
    return list(
        await db.execute(
            select(
                Attachment.id,
                Attachment.original_name,
                Attachment.size_bytes,
                Attachment.detected_mime,
                Attachment.is_image,
                Attachment.width,
                Attachment.height,
                Attachment.alt_text,
                Attachment.is_cover,
            )
            .where(Attachment.post_id == post_id, Attachment.role == literal_column("'attachment'"))
            .order_by(Attachment.sort_order, Attachment.id)
        )
    )


async def find_post_for_edit(db: AsyncSession, post_id: int) -> tuple[Row, Board] | None:
    row = (
        await db.execute(
            select(  # post-clause: exempt — 수정 화면, 호출부가 can(post.update) 판정
                Post.id,
                Post.board_id,
                Post.member_id,
                Post.is_guest,
                Post.status,
                Post.is_secret,
                Post.is_blinded,
                Post.min_view_level,
                Post.title,
                Post.content_format,
                Post.content_source,
                Post.content_html,
                Post.version,
                _category_ids(),
                Board,
            )
            .join(Board, Board.id == Post.board_id)
            .where(Post.id == post_id)
        )
    ).one_or_none()
    return (row, row.Board) if row else None
