"""글 읽기 쿼리 — 용도별 칸만 읽는다(§2.2 P3). 글 조회는 모두 판정 절을 거친다(§5.2, CI 검사).

고정 조건은 SQL 리터럴(§2.2 P4) — 목록의 is_pinned = false 는 부분 인덱스 ix_posts_board_list 의 조건과 같은 모양.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Row, Select, exists, func, literal_column, or_, select, tuple_, union_all
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


@dataclass(frozen=True)
class BoardListStatements:
    rows: Select
    count: Select
    pinned: Select | None
    cap: int


def board_list_statements(
    viewer: Viewer,
    role: BoardRole,
    board: Board,
    *,
    page: int,
    per_page: int,
    category_id: int | None = None,
    archived: bool = False,
) -> BoardListStatements:
    """게시판 목록 문장 — 실행(list_board_posts)과 측정(scripts/explain_hotpaths.py)이 같은 문장을 쓴다."""
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
    # 지연 조인 — 쪽 넘김은 id 만으로 하고(인덱스), 통계·카테고리는 그 쪽의 행에만 붙인다.
    # OFFSET 으로 버리는 행에도 조인·부분질의를 계산하던 것을 피한다(측정: 깊은 쪽 30~50ms)
    page_ids = (
        select(Post.id).where(*conds).order_by(*order).offset((page - 1) * per_page).limit(per_page)
    ).subquery()
    rows = (
        select(*LIST_COLUMNS, _category_ids())
        .join(page_ids, page_ids.c.id == Post.id)
        .outerjoin(PostStat, PostStat.post_id == Post.id)
        .order_by(*order)
    )
    cap = MAX_PAGE * per_page
    count = select(func.count()).select_from(select(Post.id).where(*conds).limit(cap + 1).subquery())
    pinned = None
    if not archived:
        pinned = (
            select(*LIST_COLUMNS, _category_ids())
            .outerjoin(PostStat, PostStat.post_id == Post.id)
            .where(*common, listable_posts_clause(viewer), Post.is_pinned == TRUE)
            .order_by(Post.pin_order.asc().nulls_last(), Post.published_at.desc())
            .limit(PINNED_LIMIT)
        )
    return BoardListStatements(rows, count, pinned, cap)


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
    st = board_list_statements(
        viewer, role, board, page=page, per_page=per_page, category_id=category_id, archived=archived
    )
    rows = list(await db.execute(st.rows))
    counted = (await db.execute(st.count)).scalar_one()
    pinned = list(await db.execute(st.pinned)) if st.pinned is not None else []
    return ListResult(pinned, rows, min(counted, st.cap), counted > st.cap)


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


def post_view_statement(post_id: int) -> Select:
    return (
        select(*VIEW_COLUMNS, _category_ids(), Board)  # post-clause: exempt — 한 건, 호출부가 can() 판정
        .join(Board, Board.id == Post.board_id)
        .outerjoin(PostStat, PostStat.post_id == Post.id)
        .where(Post.id == post_id)
    )


async def find_post_for_view(db: AsyncSession, post_id: int) -> tuple[Row, Board] | None:
    """판정 전 한 건 조회 — 권한은 호출부가 can(post.read) 로 판정한다."""
    row = (await db.execute(post_view_statement(post_id))).one_or_none()
    if row is None:
        return None
    return row, row.Board


async def is_tombstoned(db: AsyncSession, post_id: int) -> bool:
    return (
        await db.execute(select(exists().where(PostTombstone.post_id == post_id)))
    ).scalar_one()


def neighbors_statement(viewer: Viewer, board_id: int, published_at: datetime, post_id: int):
    """이전·다음 글 — 목록 인덱스를 키셋으로 재사용(§4.7). 쿼리 한 번."""
    base = (
        Post.board_id == board_id,
        listable_posts_clause(viewer),
        Post.is_pinned == FALSE,
    )
    older = (
        select(literal_column("'prev'").label("dir"), Post.id, Post.title, Post.is_secret, Post.is_blinded)
        # 행 값 비교 — (A < x OR (A = x AND id < y)) 꼴은 인덱스 범위 조건이 되지 않아 앞에서부터 걸러 읽는다(측정)
        .where(*base, tuple_(Post.published_at, Post.id) < tuple_(published_at, post_id))
        .order_by(Post.published_at.desc(), Post.id.desc())
        .limit(1)
    )
    newer = (
        select(literal_column("'next'").label("dir"), Post.id, Post.title, Post.is_secret, Post.is_blinded)
        .where(*base, tuple_(Post.published_at, Post.id) > tuple_(published_at, post_id))
        .order_by(Post.published_at.asc(), Post.id.asc())
        .limit(1)
    )
    return union_all(older, newer)


async def find_neighbors(
    db: AsyncSession, viewer: Viewer, board_id: int, published_at: datetime, post_id: int
) -> dict[str, Row | None]:
    stmt = neighbors_statement(viewer, board_id, published_at, post_id)
    found = {row.dir: row for row in await db.execute(stmt)}
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


async def list_attachments(db: AsyncSession, post_id: int, *, include_inline: bool = False) -> list[Row]:
    """글의 첨부 — 글 보기는 첨부 역할만(본문 이미지는 본문에), 수정 화면은 전부."""
    stmt = (
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
            Attachment.role,
            Attachment.storage_key,
            Attachment.visibility,
            Attachment.thumbs_ready,
        )
        .where(Attachment.post_id == post_id)
        .order_by(Attachment.sort_order, Attachment.id)
    )
    if not include_inline:
        stmt = stmt.where(Attachment.role == literal_column("'attachment'"))
    return list(await db.execute(stmt))


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


def has_restricted_statement(board_id: int) -> Select:
    """보는 사람에 따라 달라지는 공개 글이 있는지 — hide 게시판의 쪽 단위 캐시 판정(§3.3). 부분 인덱스 ix_posts_board_restricted."""
    return select(
        exists().where(
            Post.board_id == board_id,
            Post.status == literal_column("'published'"),
            or_(Post.is_secret, Post.is_blinded, Post.min_view_level > literal_column("0")),
        )  # post-clause: exempt — 게시판 단위 존재 여부만(행을 내주지 않음)
    )


async def has_restricted_posts(db: AsyncSession, board_id: int) -> bool:
    return (await db.execute(has_restricted_statement(board_id))).scalar_one()


def posts_for_state_statement(viewer: Viewer, board_id: int, ids: list[int]) -> Select:
    """개인 조각용 — 목록에 나올 수 있는 글만(지난 글 탭 포함), 판정에 필요한 칸만."""
    return select(
        Post.id,
        Post.title,
        Post.member_id,
        Post.is_guest,
        Post.status,
        Post.is_secret,
        Post.is_blinded,
        Post.min_view_level,
    ).where(
        Post.board_id == board_id,
        Post.id.in_(ids),
        or_(listable_posts_clause(viewer), listable_posts_clause(viewer, expired=True)),
    )


async def find_posts_for_state(
    db: AsyncSession, viewer: Viewer, board_id: int, ids: list[int]
) -> list[Row]:
    return list(await db.execute(posts_for_state_statement(viewer, board_id, ids)))
