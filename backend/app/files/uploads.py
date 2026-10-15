"""업로드 — 글 작성 전 임시 업로드(post_id NULL, 24시간 뒤 정리). 설계도 §3.1-3, §11, §12.

순서: 권한(attachment.upload) → 요청 수 제한 → 이미지 작업 한도(차면 429 + Retry-After) →
본문을 임시 파일로 흘려 받으며 크기 상한(413) → 앞부분으로 형식 판별·확장자 대조 →
이미지는 머리만 읽어 해상도 상한(디코딩 전) → 메타데이터 구간 제거(디코딩 없이) → 제자리로 → 행 + outbox(썸네일).
처음 자리는 언제나 비공개 저장소. 글에 붙고 글이 공개면 작업자가 공개 저장소로 옮긴다(§12.1).
"""

import hashlib
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import anyio
from fastapi import Request
from sqlalchemy import insert

from app.auth.viewer import Viewer
from app.boards.settings import UploadPolicy
from app.core import idempotency, outbox, rate_limit
from app.core.problems import Problem
from app.core.threads import limiter, run_in_thread
from app.db.session import SessionLocal
from app.files import detect, images, storage
from app.files.metadata import MetadataError, strip_metadata
from app.models import Attachment
from app.permissions import can, load_board_role
from app.posts import queries as post_queries

HEAD_BYTES = 64
MAX_NAME = 255


@dataclass(frozen=True)
class Received:
    path: Path
    size: int
    head: bytes


def _invalid(message: str, status: int = 422, code: str = "upload_rejected") -> Problem:
    return Problem(status, code, message, errors=[{"field": "file", "message": message}])


def clean_filename(raw: str | None) -> str:
    name = unquote(raw or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    name = "".join(c for c in name if c.isprintable() and c not in '<>:"|?*')
    if not name or name in (".", ".."):
        raise _invalid("파일 이름이 없습니다")
    return name[:MAX_NAME]


async def _receive(request: Request, max_bytes: int) -> Received:
    tmp = storage.tmp_dir() / f"up-{secrets.token_hex(16)}"
    size = 0
    head = b""
    try:
        async with await anyio.open_file(tmp, "wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > max_bytes:
                    raise _invalid(f"파일이 너무 큽니다(최대 {max_bytes // (1024 * 1024)}MB)", 413, "file_too_large")
                if len(head) < HEAD_BYTES:
                    head += chunk[: HEAD_BYTES - len(head)]
                await f.write(chunk)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    if size == 0:
        tmp.unlink(missing_ok=True)
        raise _invalid("빈 파일입니다")
    return Received(tmp, size, head)


def _prepare_image(path: Path, mime: str, max_px: int) -> tuple[bytes, int, int]:
    """머리만 읽어 해상도 확인 → 메타데이터 구간 제거(디코딩 없음). 스레드에서 돈다."""
    data = path.read_bytes()
    try:
        width, height = images.header_size(data)
    except Exception:
        raise _invalid("이미지를 읽을 수 없습니다") from None
    if width * height > max_px:
        raise _invalid(f"이미지 해상도가 너무 큽니다(최대 {max_px:,}화소)")
    try:
        return strip_metadata(data, mime), width, height
    except MetadataError as e:
        raise _invalid(f"이미지 구조가 올바르지 않습니다: {e}") from None


async def upload(request: Request, viewer: Viewer, board_slug: str, filename: str | None, idempotency_key: str | None) -> tuple[int, dict[str, Any]]:
    if viewer.member_id is None:
        raise Problem(401, "login_required", "로그인이 필요합니다")
    async with SessionLocal() as db:
        board = await post_queries.find_board(db, board_slug)
        if board is None:
            raise Problem(404, "board_not_found", "게시판을 찾을 수 없습니다")
        role = await load_board_role(db, viewer, board.id)
    if not can(viewer, role, "attachment.upload", board):
        raise Problem(403, "upload_forbidden", "이 게시판에 파일을 올릴 수 없습니다")
    policy = UploadPolicy.model_validate(board.upload_policy)
    name = clean_filename(filename)
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in policy.exts:
        raise _invalid(f"올릴 수 없는 파일 형식입니다(.{ext or '확장자 없음'})")

    await rate_limit.hit("upload", f"m:{viewer.member_id}")
    if limiter("image").available_tokens < 1:
        raise Problem(429, "busy", "지금은 파일 처리가 많습니다. 잠시 뒤 다시 시도해 주세요", headers={"Retry-After": "2"})

    received = await _receive(request, policy.max_bytes)
    try:
        detected = detect.detect(received.head)
        if detected is None or ext not in detected.exts:
            raise _invalid("파일 내용이 확장자와 맞지 않거나 받을 수 없는 형식입니다")
        mime = detect.mime_for(detected, ext)
        width = height = None
        if detected.is_image:
            data, width, height = await run_in_thread("image", _prepare_image, received.path, mime, policy.image_max_px)
            await anyio.Path(received.path).write_bytes(data)
            size = len(data)
        else:
            size = received.size
        sha256 = await run_in_thread("image", lambda: hashlib.sha256(received.path.read_bytes()).hexdigest())

        claim = None
        if idempotency_key is not None:
            claimed = await idempotency.claim(
                f"m:{viewer.member_id}", idempotency_key, idempotency.request_hash(f"POST /uploads?board={board_slug}", {"name": name, "sha256": sha256})
            )
            if isinstance(claimed, idempotency.Replay):
                return claimed.status_code, claimed.body
            claim = claimed

        key = storage.new_key(ext)  # ext 는 판별한 형식의 확장자 목록 안에 있다(위에서 확인)
        storage.place(received.path, "private", key)
        try:
            async with SessionLocal() as db, db.begin():
                attachment_id = (
                    await db.execute(
                        insert(Attachment)
                        .values(
                            uploader_id=viewer.member_id,
                            original_name=name,
                            storage_key=key,
                            sha256=sha256,
                            detected_mime=mime,
                            size_bytes=size,
                            is_image=detected.is_image,
                            width=width,
                            height=height,
                            exif_stripped=True,
                        )
                        .returning(Attachment.id)
                    )
                ).scalar_one()
                if detected.is_image:
                    await outbox.enqueue(db, [outbox.Event("attachment.uploaded", {"attachment_id": attachment_id})])
                body = {
                    "attachment": {
                        "id": attachment_id,
                        "name": name,
                        "size": size,
                        "mime": mime,
                        "is_image": detected.is_image,
                        "width": width,
                        "height": height,
                        "url": f"/api/attachments/{attachment_id}/file",
                        "markdown": f"![{name.rsplit('.', 1)[0]}](attachment:{attachment_id})" if detected.is_image else None,
                    }
                }
                if claim is not None:
                    await idempotency.complete(db, claim, 201, body)
        except BaseException:
            storage.delete_labels(storage.all_paths(key))
            if claim is not None:
                await idempotency.release(claim)
            raise
        return 201, body
    finally:
        received.path.unlink(missing_ok=True)
