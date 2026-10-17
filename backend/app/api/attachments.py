"""업로드·첨부 전송 — 설계도 §6, §11, §12.

전송 권한: 임시 업로드는 업로더만, 메타데이터를 못 지운 파일(exif_stripped=false)도 업로더만(§11),
본문 이미지·썸네일은 글 열람(post.read), 첨부 파일은 다운로드(attachment.download), 블록 그림은 블록 보이기(block.view —
홈블록 §4.7). 볼 수 없는 글·블록은 존재를 숨긴다(404).
"""

from typing import Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.viewer import Viewer, get_viewer
from app.core import outbox
from app.core.problems import Problem
from app.db.session import get_db
from app.files import storage, uploads
from app.files.sender import sender
from app.models import TEMP_UPLOAD, Attachment, Block, Page
from app.permissions import block_view, can, load_board_role
from app.posts import queries as post_queries

router = APIRouter()
NOT_FOUND = Problem(404, "attachment_not_found", "파일을 찾을 수 없습니다")


@router.post("/uploads", status_code=201)
async def upload(
    request: Request,
    board: str | None = Query(None, max_length=100),
    target: Literal["site"] | None = Query(None),
    filename: str | None = Header(None, alias="X-Upload-Filename"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    viewer: Viewer = Depends(get_viewer),
):
    """본문은 파일 바이트 그대로(멀티파트 아님), 이름은 X-Upload-Filename(URL 인코딩).
    대상은 board(게시판 글) 와 target=site(블록 그림, 홈블록 §4.7) 중 정확히 하나."""
    if (board is None) == (target is None):
        raise Problem(422, "validation_error", "board 와 target=site 중 하나만 보냅니다", errors=[{"field": "board", "message": "board 또는 target"}])
    status, body = await uploads.upload(request, viewer, board, filename, idempotency_key)
    return JSONResponse(body, status_code=status)


async def _block_visible(db: AsyncSession, viewer: Viewer, block_id: int) -> bool:
    """block.view ∧ 주인을 볼 수 있음 — 틀은 누구나, 페이지는 게시 ∧ 열람 등급(§6.1 page.read)"""
    blk = (
        await db.execute(
            select(Block.is_active, Block.audience, Block.min_level, Block.layout_id, Page.status, Page.view_level)
            .outerjoin(Page, Page.id == Block.page_id)
            .where(Block.id == block_id)
        )
    ).one_or_none()
    if blk is None or not block_view(viewer, blk):
        return False
    return blk.layout_id is not None or (blk.status == "published" and blk.view_level <= viewer.level)


async def _authorized(db: AsyncSession, viewer: Viewer, attachment_id: int, *, purpose: Literal["file", "thumb"]):
    row = (
        await db.execute(
            select(
                Attachment.id, Attachment.post_id, Attachment.block_id, Attachment.uploader_id, Attachment.role, Attachment.storage_key,
                Attachment.original_name, Attachment.detected_mime, Attachment.is_image, Attachment.exif_stripped,
                Attachment.thumbs_ready, Attachment.width, Attachment.height,
            ).where(Attachment.id == attachment_id)
        )
    ).one_or_none()  # fmt: skip
    if row is None:
        raise NOT_FOUND
    is_uploader = viewer.member_id is not None and row.uploader_id == viewer.member_id
    if (row.post_id is None and row.block_id is None) or not row.exif_stripped:  # 임시·메타데이터를 못 지운 파일
        if is_uploader or viewer.is_admin:
            return row
        raise NOT_FOUND
    if row.block_id is not None:  # 블록 그림(홈블록 §4.7) — 블록을 볼 수 있는 사람만, 못 보면 있는 줄 모르게 404
        if viewer.is_admin or await _block_visible(db, viewer, row.block_id):
            return row
        raise NOT_FOUND
    found = await post_queries.find_post_for_view(db, row.post_id)
    if found is None:
        raise NOT_FOUND
    post, board = found
    role = await load_board_role(db, viewer, board.id)
    if not can(viewer, role, "post.read", board, post):
        raise NOT_FOUND
    if purpose == "file" and row.role == "attachment" and not can(viewer, role, "attachment.download", board, post):
        raise Problem(403, "download_forbidden", "이 파일을 받을 수 있는 등급이 아닙니다")
    return row


@router.get("/attachments/{attachment_id}/file")
async def get_file(attachment_id: int, viewer: Viewer = Depends(get_viewer), db: AsyncSession = Depends(get_db)):
    row = await _authorized(db, viewer, attachment_id, purpose="file")
    found = storage.locate(row.storage_key)
    if found is None:
        raise NOT_FOUND
    # 이미지는 화면에 보이고, 그 밖의 파일은 내려받는다(§11 'SVG·HTML 파일')
    return sender().send(found[1], mime=row.detected_mime, filename=row.original_name, inline=row.is_image)


def _placeholder(width: int, ratio: float) -> Response:
    """썸네일이 아직 없을 때 — 크기가 고정된 자리 표시(원본을 내보내지 않는다, §12.1)."""
    height = max(1, round(width * ratio))
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"><rect width="100%" height="100%" fill="#e5e7eb"/></svg>'
    return Response(svg, media_type="image/svg+xml", headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})


@router.get("/attachments/{attachment_id}/thumb")
async def get_thumb(
    attachment_id: int,
    w: Literal["320", "640", "1280"] = "640",
    viewer: Viewer = Depends(get_viewer),
    db: AsyncSession = Depends(get_db),
):
    row = await _authorized(db, viewer, attachment_id, purpose="thumb")
    if not row.is_image:
        raise NOT_FOUND
    width = int(w)
    path = storage.locate_thumb(row.storage_key, width) if row.thumbs_ready else None
    if path is None:
        ratio = (row.height / row.width) if row.width and row.height else 0.75
        return _placeholder(width, ratio)
    return sender().send(path, mime="image/webp", filename=f"{storage.stem(row.original_name)}.webp", inline=True)


@router.delete("/attachments/{attachment_id}")
async def delete_temp(attachment_id: int, viewer: Viewer = Depends(get_viewer), db: AsyncSession = Depends(get_db)):
    """글·블록에 붙기 전의 내 임시 업로드만 지운다(붙은 첨부는 글 수정의 attachments 목록으로)."""
    if viewer.member_id is None:
        raise Problem(401, "login_required", "로그인이 필요합니다")
    key = (
        await db.execute(
            delete(Attachment)
            .where(Attachment.id == attachment_id, TEMP_UPLOAD, Attachment.uploader_id == viewer.member_id)
            .returning(Attachment.storage_key)
        )
    ).scalar_one_or_none()
    if key is None:
        raise NOT_FOUND
    await outbox.enqueue(db, [outbox.Event("files.delete", {"labels": storage.all_paths(key)})])
    await db.commit()
    return {"deleted": attachment_id}

