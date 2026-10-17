"""SEO 조회 — 비회원 기준(readable_posts_clause(GUEST)) + 게시판 indexable. 비공개 글은 여기 나오지 않는다(§10 '비공개')."""

from typing import Any

from sqlalchemy import func, literal_column, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.viewer import GUEST
from app.editor.sanitize import plain_text
from app.files.attach import thumb_template
from app.models import Attachment, Board, BoardGroup, Post
from app.permissions import guest_listable_boards_clause, guest_readable_boards_clause, readable_posts_clause

SITEMAP_SIZE = 50_000  # 검색엔진 한도(파일 하나 5만 주소)
FEED_SIZE = 30
OG_WIDTH = 1280
DESCRIPTION_CHARS = 160


def description(content_html: str) -> str:
    text = plain_text(content_html)
    return text if len(text) <= DESCRIPTION_CHARS else text[: DESCRIPTION_CHARS - 1].rstrip() + "…"


def og_image_statement(post_id: int):
    """대표 이미지 문장 — 공개 저장소에 있고 썸네일이 준비된 사진. 대표 지정이 먼저, 그다음 순서(측정 도구가 EXPLAIN 한다)."""
    return (
        select(Attachment.storage_key, Attachment.visibility, Attachment.id, Attachment.width, Attachment.height, Attachment.alt_text)
        .where(
            Attachment.post_id == post_id,
            Attachment.is_image.is_(true()),
            Attachment.thumbs_ready.is_(true()),
            Attachment.visibility == literal_column("'public'"),
        )
        .order_by(Attachment.is_cover.desc(), Attachment.sort_order, Attachment.id)
        .limit(1)
    )


async def og_image(db: AsyncSession, post_id: int) -> dict[str, Any] | None:
    row = (await db.execute(og_image_statement(post_id))).one_or_none()
    if row is None:
        return None
    scale = min(1.0, OG_WIDTH / row.width) if row.width else 1.0
    return {
        "url": thumb_template(row).format(w=OG_WIDTH),
        "width": round(row.width * scale) if row.width else None,
        "height": round(row.height * scale) if row.height else None,
        "alt": row.alt_text or "",
    }


async def menu_boards(db: AsyncSession) -> list[dict[str, str]]:
    """대체 틀의 게시판 메뉴(홈블록 설계도 §3.6) — 메뉴 노출·사용 중이고 비회원이 목록을 볼 수 있는 게시판, 분류 그룹·순서대로."""
    rows = (
        await db.execute(
            select(Board.slug, Board.name)
            .outerjoin(BoardGroup, BoardGroup.id == Board.group_id)
            .where(guest_listable_boards_clause(), Board.show_in_menu.is_(true()))
            .order_by(BoardGroup.sort_order.asc().nulls_first(), Board.sort_order, Board.id)
        )
    ).all()
    return [{"slug": r.slug, "name": r.name} for r in rows]


def _indexable_boards():
    return (guest_readable_boards_clause(), Board.indexable.is_(true()))


async def sitemap_index(db: AsyncSession) -> dict[str, Any]:
    boards = (await db.execute(select(Board.slug, Board.updated_at).where(*_indexable_boards()).order_by(Board.sort_order, Board.id))).all()
    count = (
        await db.execute(
            select(func.count()).select_from(Post).join(Board, Board.id == Post.board_id).where(readable_posts_clause(GUEST), *_indexable_boards())
        )
    ).scalar_one()
    return {
        "boards": [{"slug": b.slug, "updated_at": b.updated_at.isoformat()} for b in boards],
        "post_parts": max(1, -(-count // SITEMAP_SIZE)),
    }


async def sitemap_posts(db: AsyncSession, part: int) -> list[dict[str, Any]]:
    """글 주소 — id 순으로 SITEMAP_SIZE 씩. lastModified = content_updated_at ?? published_at."""
    rows = (
        await db.execute(
            select(Post.id, Board.slug, func.coalesce(Post.content_updated_at, Post.published_at).label("lastmod"))
            .join(Board, Board.id == Post.board_id)
            .where(readable_posts_clause(GUEST), *_indexable_boards())
            .order_by(Post.id)
            .offset(part * SITEMAP_SIZE)
            .limit(SITEMAP_SIZE)
        )
    ).all()
    return [{"id": r.id, "slug": r.slug, "lastmod": r.lastmod.isoformat() if r.lastmod else None} for r in rows]


async def feed(db: AsyncSession, board_slug: str | None) -> dict[str, Any] | None:
    """RSS — 최근 공개 글 30건(게시판 하나 또는 전체). 게시판이 색인 대상이 아니면 None."""
    board = None
    if board_slug is not None:
        board = (await db.execute(select(Board).where(Board.slug == board_slug, *_indexable_boards()))).scalar_one_or_none()
        if board is None:
            return None
    stmt = (
        select(Post.id, Post.title, Post.author_name_snapshot, Post.published_at, Post.content_rendered, Board.slug, Board.name)
        .join(Board, Board.id == Post.board_id)
        .where(readable_posts_clause(GUEST), *_indexable_boards())
        .order_by(Post.published_at.desc(), Post.id.desc())
        .limit(FEED_SIZE)
    )
    if board is not None:
        stmt = stmt.where(Post.board_id == board.id)
    rows = (await db.execute(stmt)).all()
    return {
        "board": {"slug": board.slug, "name": board.name, "description": board.description} if board else None,
        "items": [
            {
                "id": r.id,
                "title": r.title,
                "author": r.author_name_snapshot,
                "published_at": r.published_at.isoformat(),
                "description": description(r.content_rendered),
                "board": {"slug": r.slug, "name": r.name},
            }
            for r in rows
        ],
    }
