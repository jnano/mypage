"""첨부를 글에 붙이기와 공개 여부 맞추기 — 설계도 §12.1.

공개 저장소(/media, nginx 가 직접)에 두는 것: 공개 글(게시판 공개·사용 중 + post_open)의 이미지 중
본문 이미지이거나 게시판 download_level 이 0 인 것. 나머지(이미지가 아닌 파일 포함)는 비공개 — 권한 판정 뒤 전송.

- 비공개로 바뀌어야 할 때: 같은 트랜잭션에서 visibility=private 로 표시하고 content_rendered 를 비공개 주소로 다시 만든다.
  파일은 작업자가 새 storage_key 로 옮긴다(옛 /media 주소는 404). 그동안 비공개 주소는 두 저장소 중 있는 곳에서 내준다.
- 공개로 바뀌어야 할 때: 작업자가 (썸네일이 준비된 뒤) 파일 복사 → 행·content_rendered 갱신 → 커밋 → 캐시 무효화.
  (옛 파일 삭제는 커밋 뒤의 files.delete 이벤트)
작성·수정·예약 발행·작업자가 모두 reconcile() 을 거친다.
"""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Row, delete, select, true, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.viewer import Viewer
from app.core import outbox
from app.core.problems import Problem
from app.editor.render import ImageSource, inline_ids, render_content
from app.files import storage
from app.models import Attachment, Board, Post
from app.search.index import post_open

ROW_COLUMNS = (
    Attachment.id,
    Attachment.post_id,
    Attachment.uploader_id,
    Attachment.role,
    Attachment.storage_key,
    Attachment.visibility,
    Attachment.is_image,
    Attachment.width,
    Attachment.height,
    Attachment.thumbs_ready,
)


def post_is_public(board: Any, *, status: str, is_secret: bool, is_blinded: bool, min_view_level: int | None) -> bool:
    return bool(
        board.is_active
        and board.list_level == 0
        and board.read_level == 0
        and post_open(status, is_secret, is_blinded, min_view_level)
    )


def desired_visibility(*, post_public: bool, is_image: bool, role: str, download_level: int) -> storage.Visibility:
    if post_public and is_image and (role == "inline" or download_level == 0):
        return "public"
    return "private"


def thumb_template(row: Any) -> str:
    if row.visibility == "public":
        return f"/media/{row.storage_key[:2]}/{storage.stem(row.storage_key)}.w{{w}}.webp"
    return f"/api/attachments/{row.id}/thumb?w={{w}}"


def image_sources(rows: Sequence[Any]) -> dict[int, ImageSource]:
    return {
        r.id: ImageSource(thumb_template(r), r.width, r.height, r.thumbs_ready) for r in rows if r.is_image
    }


async def load_for_post(db: AsyncSession, post_id: int) -> list[Row]:
    return list(
        await db.execute(select(*ROW_COLUMNS).where(Attachment.post_id == post_id).order_by(Attachment.sort_order, Attachment.id))  # post-clause: exempt — 첨부 칸(글 아님)
    )


async def load_attachable(db: AsyncSession, viewer: Viewer, ids: Sequence[int], post_id: int | None) -> list[Row]:
    """붙일 수 있는 첨부 — 내 임시 업로드이거나 이미 이 글의 것. 아니면 422."""
    if not ids:
        return []
    rows = {r.id: r for r in await db.execute(select(*ROW_COLUMNS).where(Attachment.id.in_(list(ids))))}  # post-clause: exempt — 첨부 칸(글 아님)
    for i in ids:
        r = rows.get(i)
        mine_temp = r is not None and r.post_id is None and r.uploader_id == viewer.member_id
        this_post = r is not None and post_id is not None and r.post_id == post_id
        if not (mine_temp or this_post):
            raise Problem(
                422, "validation_error", "입력값이 올바르지 않습니다",
                errors=[{"field": "attachments", "message": f"붙일 수 없는 첨부입니다: {i}"}],
            )  # fmt: skip
    return [rows[i] for i in ids]


async def apply(
    db: AsyncSession, post_id: int, items: Sequence[Any], *, used_inline: set[int], remove_others: bool
) -> None:
    """순서·대체 텍스트·대표 사진·역할을 적용한다. remove_others 면 목록에 없는 이 글의 첨부를 지운다."""
    cover_taken = False
    for index, item in enumerate(items):
        cover = bool(item.is_cover) and not cover_taken
        cover_taken |= cover
        await db.execute(
            update(Attachment)
            .where(Attachment.id == item.id)
            .values(
                post_id=post_id,
                sort_order=index,
                alt_text=item.alt_text,
                is_cover=cover,
                role="inline" if item.id in used_inline else "attachment",
            )
        )
    if remove_others:
        keep = [i.id for i in items]
        gone = (
            await db.execute(
                delete(Attachment)
                .where(Attachment.post_id == post_id, Attachment.id.not_in(keep) if keep else true())
                .returning(Attachment.storage_key)
            )
        ).scalars().all()
        labels = [label for key in gone for label in storage.all_paths(key)]
        if labels:
            await outbox.enqueue(db, [outbox.Event("files.delete", {"labels": labels})])


async def rerender(db: AsyncSession, post_id: int, content_html: str, rows: Sequence[Any]) -> None:
    await db.execute(
        update(Post).where(Post.id == post_id).values(content_rendered=render_content(content_html, image_sources(rows)))
    )


async def reconcile(db: AsyncSession, post_id: int) -> None:
    """트랜잭션 안: 비공개여야 할 첨부를 바로 비공개로 표시하고 본문을 다시 렌더한다. 옮길 파일이 있을 수 있으면 작업자에게."""
    post = (
        await db.execute(
            select(  # post-clause: exempt — 첨부 공개 여부 계산(판정은 post_is_public)
                Post.id, Post.board_id, Post.status, Post.is_secret, Post.is_blinded, Post.min_view_level, Post.content_html
            ).where(Post.id == post_id)
        )
    ).one_or_none()
    if post is None:
        return
    rows = await load_for_post(db, post_id)
    if not rows:
        return
    board = (await db.execute(select(Board).where(Board.id == post.board_id))).scalar_one()
    public = post_is_public(board, status=post.status, is_secret=post.is_secret, is_blinded=post.is_blinded, min_view_level=post.min_view_level)
    demote = [
        r.id for r in rows
        if r.visibility == "public"
        and desired_visibility(post_public=public, is_image=r.is_image, role=r.role, download_level=board.download_level) == "private"
    ]  # fmt: skip
    if demote:
        await db.execute(update(Attachment).where(Attachment.id.in_(demote)).values(visibility="private"))
        rows = await load_for_post(db, post_id)
    await rerender(db, post_id, post.content_html, rows)
    await outbox.enqueue(db, [outbox.Event("attachments.sync", {"post_id": post_id})])
