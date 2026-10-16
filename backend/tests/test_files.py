"""첨부(§11·§12) — 형식 판별·메타데이터 제거·업로드 검증, 전송 권한, 글에 붙이기, 공개 여부 맞추기, 정리."""

import io
from pathlib import Path
from urllib.parse import quote

import pytest
from httpx import AsyncClient
from PIL import Image, PngImagePlugin
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.files import detect, storage
from app.files.metadata import MetadataError, strip_metadata
from app.db.session import SessionLocal
from app.models import Attachment, Board, BoardCategory, Member, OutboxEvent
from app.posts.purge import purge_posts
from app.worker import handlers  # noqa: F401 — 처리기 등록
from app.worker.core import process_available
from tests.factories import make_board, make_member
from tests.helpers import as_member

pytestmark = pytest.mark.anyio


def jpeg_with_gps(size=(64, 32), orientation=6) -> bytes:
    img = Image.new("RGB", size, "red")
    exif = img.getexif()
    exif[0x0112] = orientation
    exif[0x010F] = "Camera"
    exif.get_ifd(0x8825).update({1: "N", 2: (37.0, 30.0, 0.0)})
    b = io.BytesIO()
    img.save(b, "JPEG", exif=exif.tobytes())
    return b.getvalue()


# ── 형식 판별·메타데이터(순수) ─────────────────────────────


@pytest.mark.parametrize(
    ("head", "mime"),
    [
        (b"\xff\xd8\xff\xe0", "image/jpeg"),
        (b"\x89PNG\r\n\x1a\n", "image/png"),
        (b"GIF89a", "image/gif"),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp"),
        (b"%PDF-1.7", "application/pdf"),
        (b"PK\x03\x04", "application/zip"),
        ("한글 텍스트".encode(), "text/plain"),
    ],
)
def test_detect(head: bytes, mime: str) -> None:
    detected = detect.detect(head)
    assert detected is not None and detected.mime == mime


@pytest.mark.parametrize("head", [b"<svg xmlns=", b"  <!DOCTYPE html>", b"<?xml version", b"\x00\x01\x02binary"])
def test_detect_rejects_markup_and_binary(head: bytes) -> None:
    assert detect.detect(head) is None


def test_strip_jpeg_keeps_orientation_only() -> None:
    out = strip_metadata(jpeg_with_gps(), "image/jpeg")
    with Image.open(io.BytesIO(out)) as im:
        im.load()
        exif = im.getexif()
        assert exif.get(0x0112) == 6 and 0x010F not in exif and not exif.get_ifd(0x8825)


def test_strip_png_text_and_broken_input() -> None:
    info = PngImagePlugin.PngInfo()
    info.add_text("Comment", "secret location")
    b = io.BytesIO()
    Image.new("RGB", (4, 4)).save(b, "PNG", pnginfo=info)
    assert b"secret" not in strip_metadata(b.getvalue(), "image/png")
    with pytest.raises(MetadataError):
        strip_metadata(b"\xff\xd8\xff\xe0\x00", "image/jpeg")


# ── 업로드 ───────────────────────────────────────────────


async def _upload(client: AsyncClient, member_id: int, data: bytes, name: str, board="free", **headers):
    return await client.post(
        f"/api/uploads?board={board}",
        content=data,
        headers=as_member(member_id) | {"X-Upload-Filename": quote(name), "Content-Type": "application/octet-stream"} | headers,
    )


async def _setup(db: AsyncSession, **board_kw):
    member = await make_member(db, level=1)
    other = await make_member(db, level=1)
    board = await make_board(db, slug="free", editor="markdown", allow_secret=True, **board_kw)
    db.add(BoardCategory(board_id=board.id, name="일반"))
    await db.commit()
    # 숫자 id 를 돌려준다 — 뒤의 expire_all() 이후 ORM 속성을 읽으면 async 에서 지연 로딩이 된다
    return member.id, other.id, board


async def test_upload_image_strips_and_thumbnails(dev_header, committed_db, client, file_roots: Path) -> None:
    mid, _, _ = await _setup(committed_db)
    res = await _upload(client, mid, jpeg_with_gps(), "회의 사진.JPG")
    assert res.status_code == 201, res.text
    a = res.json()["attachment"]
    assert (a["mime"], a["is_image"], a["width"], a["height"]) == ("image/jpeg", True, 64, 32)
    assert a["markdown"] == f"![회의 사진](attachment:{a['id']})"

    row = (await committed_db.execute(select(Attachment).where(Attachment.id == a["id"]))).scalar_one()
    assert (row.post_id, row.visibility, row.exif_stripped, row.thumbs_ready) == (None, "private", True, False)
    stored = storage.file_path("private", row.storage_key).read_bytes()
    with Image.open(io.BytesIO(stored)) as im:
        assert not im.getexif().get_ifd(0x8825)  # 위치 정보 없음
    assert row.storage_key.endswith(".jpg")

    await process_available(10)  # 썸네일
    committed_db.expire_all()
    row = (await committed_db.execute(select(Attachment).where(Attachment.id == a["id"]))).scalar_one()
    # 회전(6 = 90도)을 반영해 폭·높이가 바뀐다
    assert (row.thumbs_ready, row.width, row.height) == (True, 32, 64)
    for w in storage.THUMB_WIDTHS:
        assert storage.thumb_path("private", row.storage_key, w).is_file()


@pytest.mark.parametrize(
    ("data", "name", "status", "fragment"),
    [
        (b"<svg xmlns='http://www.w3.org/2000/svg'></svg>", "a.svg", 422, "올릴 수 없는 파일 형식"),
        (b"<html><script>x</script></html>", "a.txt", 422, "확장자와 맞지 않"),
        (b"%PDF-1.7 ...", "photo.jpg", 422, "확장자와 맞지 않"),
        (b"", "a.txt", 422, "빈 파일"),
        (b"plain", "noext", 422, "올릴 수 없는 파일 형식"),
    ],
)
async def test_upload_rejections(dev_header, committed_db, client, data, name, status, fragment) -> None:
    mid, _, _ = await _setup(committed_db)
    res = await _upload(client, mid, data, name)
    assert res.status_code == status and fragment in res.json()["errors"][0]["message"], res.text


async def test_upload_limits(dev_header, committed_db, client) -> None:
    mid, _, board = await _setup(committed_db)
    policy = dict(board.upload_policy) | {"max_bytes": 100, "image_max_px": 100}
    await committed_db.execute(update(Board).where(Board.id == board.id).values(upload_policy=policy))
    await committed_db.commit()
    assert (await _upload(client, mid, b"x" * 101, "a.txt")).status_code == 413
    big = io.BytesIO()
    Image.new("RGB", (20, 20)).save(big, "PNG")  # 400화소 > 100
    res = await _upload(client, mid, big.getvalue(), "a.png")
    assert res.status_code in (413, 422)
    assert (await client.post("/api/uploads?board=free", content=b"x")).status_code == 401
    assert (await _upload(client, mid, b"x", "a.txt", board="nothing")).status_code == 404


# ── 글에 붙이기·공개 여부·전송 권한 ───────────────────────


async def _post_with_image(client, member_id: int, *, is_secret=False) -> tuple[int, int]:
    a = (await _upload(client, member_id, jpeg_with_gps(), "사진.jpg")).json()["attachment"]
    res = await client.post(
        "/api/boards/free/posts",
        json={"title": "사진 글", "content": f"본문\n\n{a['markdown']}", "is_secret": is_secret,
              "attachments": [{"id": a["id"], "alt_text": "회의실", "is_cover": True}]},  # fmt: skip
        headers=as_member(member_id),
    )
    assert res.status_code == 201, res.text
    return res.json()["post"]["id"], a["id"]


async def _attachment(db: AsyncSession, attachment_id: int) -> Attachment:
    db.expire_all()
    return (await db.execute(select(Attachment).where(Attachment.id == attachment_id))).scalar_one()


async def test_public_post_image_moves_to_public_storage(dev_header, committed_db, client) -> None:
    mid, _, _ = await _setup(committed_db)
    post_id, att_id = await _post_with_image(client, mid)
    row = await _attachment(committed_db, att_id)
    assert (row.post_id, row.role, row.alt_text, row.is_cover, row.visibility) == (post_id, "inline", "회의실", True, "private")
    page = (await client.get(f"/api/posts/{post_id}/page")).json()
    assert f'data-attachment-id="{att_id}"' in page["post"]["content_html"] and "data-pending" in page["post"]["content_html"]

    await process_available(50)  # 썸네일 → 공개 저장소로 옮김 → 본문 다시 렌더
    row = await _attachment(committed_db, att_id)
    assert row.visibility == "public" and storage.file_path("public", row.storage_key).is_file()
    assert not storage.file_path("private", row.storage_key).exists()  # 옛 파일은 files.delete 로
    html = (await client.get(f"/api/posts/{post_id}/page")).json()["post"]["content_html"]
    assert f"/media/{row.storage_key[:2]}/{storage.stem(row.storage_key)}.w640.webp" in html
    assert 'alt="사진"' in html


async def test_secret_post_keeps_files_private_and_gated(dev_header, committed_db, client) -> None:
    mid, oid, _ = await _setup(committed_db)
    post_id, att_id = await _post_with_image(client, mid, is_secret=True)
    await process_available(50)
    row = await _attachment(committed_db, att_id)
    assert row.visibility == "private"
    html = (await client.get(f"/api/posts/{post_id}/page", headers=as_member(mid))).json()["post"]["content_html"]
    assert f"/api/attachments/{att_id}/thumb?w=640" in html

    ok = await client.get(f"/api/attachments/{att_id}/file", headers=as_member(mid))
    assert ok.status_code == 200 and ok.headers["x-content-type-options"] == "nosniff"
    assert ok.headers["content-disposition"].startswith("inline;") and "filename*=UTF-8''%EC%82%AC%EC%A7%84.jpg" in ok.headers["content-disposition"]
    assert (await client.get(f"/api/attachments/{att_id}/file", headers=as_member(oid))).status_code == 404
    assert (await client.get(f"/api/attachments/{att_id}/thumb?w=320")).status_code == 404


async def test_going_private_demotes_in_same_transaction(dev_header, committed_db, client) -> None:
    mid, _, _ = await _setup(committed_db)
    post_id, att_id = await _post_with_image(client, mid)
    await process_available(50)
    public_key = (await _attachment(committed_db, att_id)).storage_key
    res = await client.patch(f"/api/posts/{post_id}", json={"is_secret": True}, headers=as_member(mid) | {"If-Match": '"1"'})
    assert res.status_code == 200
    row = await _attachment(committed_db, att_id)
    assert row.visibility == "private"  # 같은 트랜잭션에서
    html = (await client.get(f"/api/posts/{post_id}/page", headers=as_member(mid))).json()["post"]["content_html"]
    assert "/media/" not in html and f"/api/attachments/{att_id}/thumb" in html
    # 파일이 아직 공개 저장소에 있어도 권한 판정 뒤 내준다
    assert (await client.get(f"/api/attachments/{att_id}/file", headers=as_member(mid))).status_code == 200
    await process_available(50)  # 작업자가 새 키로 비공개 저장소에
    row = await _attachment(committed_db, att_id)
    assert row.storage_key != public_key and storage.file_path("private", row.storage_key).is_file()
    assert not storage.file_path("public", public_key).exists()  # 옛 /media 주소는 404


async def test_attach_rules(dev_header, committed_db, client) -> None:
    mid, oid, board = await _setup(committed_db)
    theirs = (await _upload(client, oid, b"hello", "a.txt")).json()["attachment"]["id"]
    res = await client.post(
        "/api/boards/free/posts",
        json={"title": "t", "content": "c", "attachments": [{"id": theirs}]},
        headers=as_member(mid),
    )
    assert res.status_code == 422  # 남의 임시 업로드는 붙일 수 없다
    mine = (await _upload(client, mid, b"hello", "a.txt")).json()["attachment"]["id"]
    res = await client.post(
        "/api/boards/free/posts", json={"title": "t", "content": f"![x](attachment:{mine})", "attachments": [{"id": mine}]},
        headers=as_member(mid),
    )
    assert res.status_code == 422  # 이미지가 아닌 첨부는 본문 이미지로 쓸 수 없다


async def test_update_removes_detached_files(dev_header, committed_db, client) -> None:
    mid, _, _ = await _setup(committed_db)
    post_id, att_id = await _post_with_image(client, mid)
    await process_available(50)
    key = (await _attachment(committed_db, att_id)).storage_key
    res = await client.patch(
        f"/api/posts/{post_id}", json={"content": "사진 뺌", "attachments": []}, headers=as_member(mid) | {"If-Match": '"1"'}
    )
    assert res.status_code == 200
    await process_available(50)
    assert (await committed_db.execute(select(Attachment.id))).all() == []
    assert not any(storage.file_path(v, key).exists() for v in ("public", "private"))


async def test_temp_upload_delete_and_purge_cleanup(dev_header, committed_db, client) -> None:
    mid, oid, _ = await _setup(committed_db)
    att = (await _upload(client, mid, b"hello", "a.txt")).json()["attachment"]["id"]
    assert (await client.delete(f"/api/attachments/{att}", headers=as_member(oid))).status_code == 404
    assert (await client.delete(f"/api/attachments/{att}", headers=as_member(mid))).json() == {"deleted": att}
    await process_available(50)
    assert not any((Path(settings.private_root)).rglob("*.txt"))

    post_id, att_id = await _post_with_image(client, mid)
    await process_available(50)
    key = (await _attachment(committed_db, att_id)).storage_key
    async with SessionLocal() as s, s.begin():
        await purge_posts(s, [post_id])
    await process_available(50)
    assert not any(storage.file_path(v, key).exists() for v in ("public", "private"))
    assert not storage.thumb_path("public", key, 320).exists()


async def test_block_image_is_not_temp(dev_header, committed_db, client) -> None:
    """블록에 붙은 그림은 임시가 아니다 — 임시 삭제·글에 붙이기 모두 안 된다(홈블록 §4.7)"""
    mid, _, _ = await _setup(committed_db)
    att = (await _upload(client, mid, jpeg_with_gps(), "배너.jpg")).json()["attachment"]["id"]
    page_id = (await committed_db.execute(text("INSERT INTO pages (path, title) VALUES ('/about', '소개') RETURNING id"))).scalar_one()
    block_id = (
        await committed_db.execute(
            text("INSERT INTO blocks (page_id, type, config) VALUES (:p, 'image', '{}') RETURNING id"), {"p": page_id}
        )
    ).scalar_one()
    await committed_db.execute(update(Attachment).where(Attachment.id == att).values(block_id=block_id))
    await committed_db.commit()
    assert (await client.delete(f"/api/attachments/{att}", headers=as_member(mid))).status_code == 404
    res = await client.post(
        "/api/boards/free/posts", json={"title": "글", "content": "본문", "attachments": [{"id": att}]}, headers=as_member(mid)
    )
    assert res.status_code == 422
    assert (await _attachment(committed_db, att)).block_id == block_id


async def test_non_image_attachment_downloads(dev_header, committed_db, client) -> None:
    mid, _, board = await _setup(committed_db, download_level=2)
    doc = (await _upload(client, mid, "회의록".encode(), "회의록.txt")).json()["attachment"]["id"]
    res = await client.post(
        "/api/boards/free/posts", json={"title": "자료", "content": "첨부 참고", "attachments": [{"id": doc}]},
        headers=as_member(mid),
    )
    post_id = res.json()["post"]["id"]
    await process_available(50)
    row = await _attachment(committed_db, doc)
    assert (row.role, row.visibility) == ("attachment", "private")  # 이미지가 아닌 파일은 늘 비공개
    page = (await client.get(f"/api/posts/{post_id}/page")).json()
    assert page["attachments"][0]["url"] == f"/api/attachments/{doc}/file"
    assert (await client.get(f"/api/attachments/{doc}/file")).status_code == 403  # download_level 2
    res = await client.get(f"/api/attachments/{doc}/file", headers=as_member(mid))
    assert res.status_code == 403  # 작성자도 레벨 1
    await committed_db.execute(update(Member).where(Member.id == mid).values(level=2))
    await committed_db.commit()
    res = await client.get(f"/api/attachments/{doc}/file", headers=as_member(mid))
    assert res.status_code == 200 and res.headers["content-disposition"].startswith("attachment;")
    assert res.text == "회의록"
    events = [e for e, in (await committed_db.execute(select(OutboxEvent.type))).all()]
    assert "attachments.sync" in events
