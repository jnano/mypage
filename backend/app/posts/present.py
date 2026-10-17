"""응답 모양 — 묶음 응답(§3.6)이 쓰는 직렬화. 가림(mask) 판정은 permissions.post_mask 한 곳."""

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Row

from app.auth.viewer import Viewer
from app.files.attach import thumb_template
from app.models import Board
from app.permissions import BoardRole, post_mask

EDITED_AFTER = timedelta(minutes=5)  # '수정됨' 표시 기준(§4.3)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def mask_reason(viewer: Viewer, role: BoardRole, row: Row) -> str | None:
    if not post_mask(viewer, role, row):
        return None
    if row.is_blinded:
        return "blinded"
    if row.is_secret:
        return "secret"
    return "level"


def board_summary(board: Board) -> dict[str, Any]:
    return {
        "id": board.id,
        "slug": board.slug,
        "name": board.name,
        "description": board.description,
        "kind": board.kind,
        "editor": board.editor,
        "display": board.display,
        "hidden_post_listing": board.hidden_post_listing,
        "pinned_display": board.pinned_display,
        "allow_secret": board.allow_secret,
        "allow_comments": board.allow_comments,
        "allow_share": board.allow_share,
        "posts_per_page": board.posts_per_page,
        "indexable": board.indexable,
        "is_public": board.list_level == 0 and board.read_level == 0,
    }


def list_row(viewer: Viewer, role: BoardRole, row: Row, now: datetime) -> dict[str, Any]:
    reason = mask_reason(viewer, role, row)
    return {
        "id": row.id,
        "title": None if reason else row.title,
        "masked": reason,
        "title_bold": row.title_bold and not reason,
        "title_color": None if reason else row.title_color,
        "author_name": row.author_name_snapshot,
        "author_is_guest": row.is_guest,  # 화면이 '(비회원)'을 붙인다 — 사칭 구분(§6.3)
        "posted_as": row.posted_as,
        "published_at": _iso(row.published_at),
        "edited": _edited(row.published_at, row.content_updated_at),
        "is_secret": row.is_secret,
        "is_pinned": row.is_pinned,
        "expired": row.expires_at is not None and row.expires_at <= now,
        "category_ids": list(row.category_ids or []),
        "stats": {
            "views": row.view_count or 0,
            "likes": row.like_count or 0,
            "comments": row.comment_count or 0,
        },
    }


def _edited(published_at: datetime | None, content_updated_at: datetime | None) -> bool:
    return bool(published_at and content_updated_at and content_updated_at > published_at + EDITED_AFTER)


def neighbor(viewer: Viewer, role: BoardRole, row: Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    hidden = (row.is_secret or row.is_blinded) and not (viewer.is_admin or role.is_moderator)
    return {"id": row.id, "title": None if hidden else row.title}


def post_view(row: Row, board: Board, now: datetime) -> dict[str, Any]:
    return {
        "id": row.id,
        "title": row.title,
        "title_bold": row.title_bold,
        "title_color": row.title_color,
        "author_name": row.author_name_snapshot,
        "author_is_guest": row.is_guest,  # 화면이 '(비회원)'을 붙인다 — 사칭 구분(§6.3)
        "posted_as": row.posted_as,
        "status": row.status,
        "content_format": row.content_format,
        "content_html": row.content_rendered,  # 읽기용(주소·iframe 채운 것)
        "published_at": _iso(row.published_at),
        "content_updated_at": _iso(row.content_updated_at),
        "edited": _edited(row.published_at, row.content_updated_at),
        "expired": row.expires_at is not None and row.expires_at <= now,
        "is_pinned": row.is_pinned,
        "is_secret": row.is_secret,
        "category_ids": list(row.category_ids or []),
        "version": row.version,
        "stats": {
            "views": row.view_count or 0,
            "likes": row.like_count or 0,
            "comments": row.comment_count or 0,
            "scraps": row.scrap_count or 0,
            "shares": row.share_count or 0,
        },
        # 공개 색인 대상인지(§10) — 비공개 글은 메타에 제목·본문을 넣지 않는다
        "indexable": bool(
            board.indexable
            and board.is_active
            and board.list_level == 0
            and board.read_level == 0
            and row.status == "published"
            and not row.is_secret
            and not row.is_blinded
            and not row.min_view_level
        ),
    }


def attachment_item(a: Row) -> dict[str, Any]:
    return {
        "id": a.id,
        "name": a.original_name,
        "size": a.size_bytes,
        "mime": a.detected_mime,
        "is_image": a.is_image,
        "width": a.width,
        "height": a.height,
        "alt": a.alt_text,
        "is_cover": a.is_cover,
        "role": a.role,
        "url": f"/api/attachments/{a.id}/file",
        "thumb": thumb_template(a).format(w=320) if a.is_image and a.thumbs_ready else None,
    }
