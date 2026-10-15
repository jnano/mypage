"""댓글 응답 모양. 지운 댓글·블라인드 댓글은 내용을 내주지 않는다(담당자·운영자는 블라인드 내용을 본다)."""

from typing import Any

from sqlalchemy import Row

from app.auth.viewer import Viewer
from app.comments.queries import Cursor
from app.permissions import BoardRole


def comment_row(viewer: Viewer, role: BoardRole, row: Row) -> dict[str, Any]:
    staff = viewer.is_admin or role.is_moderator
    masked = None
    if row.status == "deleted":
        masked = "deleted"
    elif row.is_blinded and not staff:
        masked = "blinded"
    return {
        "id": row.id,
        "parent_id": row.parent_id,
        "reply_to": (
            {"id": row.reply_to_comment_id, "author_name": row.reply_to_name}
            if row.reply_to_comment_id is not None and row.reply_to_comment_id != row.parent_id
            else None
        ),
        # 화면이 개인 조각의 viewer.member_id 와 견줘 수정·삭제 단추를 보인다(추가 호출 없이)
        "author_id": None if masked == "deleted" else row.member_id,
        "author_name": None if masked == "deleted" else row.author_name_snapshot,
        "content": None if masked else row.content,
        "masked": masked,
        "is_blinded": row.is_blinded,
        "edited": row.edited_at is not None,
        "created_at": row.created_at.isoformat(),
    }


def comments_page(viewer: Viewer, role: BoardRole, rows: list[Row], next_cursor: Cursor | None) -> dict[str, Any]:
    return {
        "items": [comment_row(viewer, role, r) for r in rows],
        "next_cursor": next_cursor.encode() if next_cursor else None,
    }
