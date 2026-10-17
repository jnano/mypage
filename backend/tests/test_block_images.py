"""사이트 업로드·블록 그림 — 홈블록 설계도 §4.7·§5.3·§11·§13('사이트 업로드(B-3)')."""

from urllib.parse import quote

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.files import storage
from app.models import Attachment, OutboxEvent
from app.worker import handlers  # noqa: F401 — 처리기 등록
from app.worker.core import process_available
from tests.factories import make_board, make_member
from tests.helpers import as_member
from tests.test_files import jpeg_with_gps

pytestmark = pytest.mark.anyio


async def _upload(client, member_id: int, data: bytes, name: str, query: str = "target=site"):
    headers = as_member(member_id) | {"X-Upload-Filename": quote(name), "Content-Type": "application/octet-stream"}
    return await client.post(f"/api/uploads?{query}", content=data, headers=headers)


async def _setup(db: AsyncSession):
    admin = await make_member(db, level=9, is_admin=True)
    user = await make_member(db, level=1)
    await make_board(db, slug="free")
    await db.commit()
    return admin.id, user.id


async def _layout(client, admin: int) -> int:
    res = await client.post("/api/admin/layouts", json={"name": "기본"}, headers=as_member(admin))
    lid = res.json()["id"]
    await client.post(f"/api/admin/layouts/{lid}/default", headers=as_member(admin))
    return lid


async def _save(client, admin: int, lid: int, version: int, regions: dict):
    return await client.put(f"/api/admin/layouts/{lid}", json={"name": "기본", "regions": regions}, headers=as_member(admin) | {"If-Match": f'"{version}"'})


def image_block(attachment_id: int, **kw) -> dict:
    return {"type": "image", "config": {"attachment_id": attachment_id, "alt": "회의실"}, **kw}


async def _row(db: AsyncSession, attachment_id: int) -> Attachment:
    db.expire_all()
    return (await db.execute(select(Attachment).where(Attachment.id == attachment_id))).scalar_one()


async def test_site_upload_rules(dev_header, committed_db, client) -> None:
    admin, user = await _setup(committed_db)
    res = await _upload(client, admin, jpeg_with_gps(), "배너.jpg")
    assert res.status_code == 201, res.text
    assert (await _upload(client, user, jpeg_with_gps(), "배너.jpg")).status_code == 403  # 운영자만(U-3)
    assert (await _upload(client, admin, b"%PDF-1.7 x", "안내.pdf")).status_code == 422  # 그림 형식만(site_upload)
    assert (await _upload(client, admin, jpeg_with_gps(), "a.jpg", "target=site&board=free")).status_code == 422  # 둘 다
    headers = as_member(admin) | {"X-Upload-Filename": "a.jpg", "Content-Type": "application/octet-stream"}
    assert (await client.post("/api/uploads", content=jpeg_with_gps(), headers=headers)).status_code == 422  # 둘 다 없음
    # 한도는 사이트 설정 묶음 — 형식을 줄이면 바로 막힌다
    await client.patch("/api/admin/settings/site_upload", json={"exts": ["png"]}, headers=as_member(admin))
    assert (await _upload(client, admin, jpeg_with_gps(), "배너.jpg")).status_code == 422
    res = await client.patch("/api/admin/settings/site_upload", json={"exts": ["pdf"]}, headers=as_member(admin))
    assert res.status_code == 422  # 그림이 아닌 형식은 설정할 수 없다


async def test_public_block_image_moves_to_public_storage(dev_header, committed_db, client) -> None:
    admin, user = await _setup(committed_db)
    att = (await _upload(client, admin, jpeg_with_gps(), "배너.jpg")).json()["attachment"]["id"]
    await process_available(50)  # 썸네일
    lid = await _layout(client, admin)
    assert (await _save(client, admin, lid, 1, {"top": [image_block(att)]})).status_code == 200
    await process_available(50)  # attach.reconcile_block → 공개 저장소로 + 캐시 무효화
    row = await _row(committed_db, att)
    assert row.visibility == "public" and storage.locate(row.storage_key)[0] == "public"
    revalidated = (await committed_db.execute(select(OutboxEvent.payload).where(OutboxEvent.type == "cache.revalidate"))).scalars().all()
    assert any(f"layout:{lid}" in p["now"] for p in revalidated)
    frame = (await client.get("/api/frame")).json()
    src = frame["layout"]["regions"]["top"][0]["data"]["image"]["src"]
    assert src.startswith("/media/") and src.endswith(".w640.webp")


async def test_member_block_image_is_private_and_served_by_block_view(dev_header, committed_db, client) -> None:
    admin, user = await _setup(committed_db)
    att = (await _upload(client, admin, jpeg_with_gps(), "회원.jpg")).json()["attachment"]["id"]
    await process_available(50)
    lid = await _layout(client, admin)
    saved = (await _save(client, admin, lid, 1, {"top": [image_block(att)]})).json()
    await process_available(50)
    assert (await _row(committed_db, att)).visibility == "public"
    block = saved["regions"]["top"][0]
    # 회원 대상으로 바꾸면 비공개 표시는 저장 트랜잭션 안에서 바로(좁히는 쪽 먼저), 파일은 작업자가
    assert (await _save(client, admin, lid, 2, {"top": [{"id": block["id"], **image_block(att), "audience": "member"}]})).status_code == 200
    assert (await _row(committed_db, att)).visibility == "private"
    await process_available(50)
    row = await _row(committed_db, att)
    assert storage.locate(row.storage_key)[0] == "private"
    # 내려주기: 블록을 볼 수 있는 사람만(B-3) — 비회원 404, 회원 200
    assert (await client.get(f"/api/attachments/{att}/thumb")).status_code == 404
    assert (await client.get(f"/api/attachments/{att}/thumb", headers=as_member(user))).status_code == 200
    assert (await client.get(f"/api/attachments/{att}/file", headers=as_member(user))).status_code == 200


async def test_public_block_image_served_to_guest_via_api_too(dev_header, committed_db, client) -> None:
    """대조군: 내려주기 가지를 빼면 비회원 공개 블록 그림이 404 가 되어 이 시험이 실패한다(§13 B-3)"""
    admin, _ = await _setup(committed_db)
    att = (await _upload(client, admin, jpeg_with_gps(), "공개.jpg")).json()["attachment"]["id"]
    lid = await _layout(client, admin)
    await _save(client, admin, lid, 1, {"top": [image_block(att)]})
    assert (await client.get(f"/api/attachments/{att}/thumb")).status_code == 200


async def test_released_images_leave_public_storage(dev_header, committed_db, client) -> None:
    """블록에서 빼거나 블록·틀을 지우면 그림은 임시 — 24시간 정리까지 공개 저장소에 남지 않는다"""
    admin, _ = await _setup(committed_db)
    a = (await _upload(client, admin, jpeg_with_gps(), "가.jpg")).json()["attachment"]["id"]
    b = (await _upload(client, admin, jpeg_with_gps(), "나.jpg")).json()["attachment"]["id"]
    await process_available(50)
    lid = await _layout(client, admin)
    await _save(client, admin, lid, 1, {"top": [image_block(a)], "bottom": [image_block(b)]})
    await process_available(50)
    assert {(await _row(committed_db, i)).visibility for i in (a, b)} == {"public"}
    saved = (await client.get(f"/api/admin/layouts/{lid}", headers=as_member(admin))).json()
    keep = saved["regions"]["top"][0]
    assert (await _save(client, admin, lid, 2, {"top": [{"id": keep["id"], **image_block(a)}]})).status_code == 200  # b 를 뺀다
    row = await _row(committed_db, b)
    assert (row.block_id, row.visibility) == (None, "private")
    await process_available(50)
    assert storage.locate((await _row(committed_db, b)).storage_key)[0] == "private"
    other = (await client.post("/api/admin/layouts", json={"name": "다른 틀"}, headers=as_member(admin))).json()["id"]
    await client.post(f"/api/admin/layouts/{other}/default", headers=as_member(admin))
    assert (await client.delete(f"/api/admin/layouts/{lid}", headers=as_member(admin))).status_code == 200
    row = await _row(committed_db, a)
    assert (row.block_id, row.visibility) == (None, "private")


async def test_images_per_block_limit(dev_header, committed_db, client) -> None:
    admin, _ = await _setup(committed_db)
    lid = await _layout(client, admin)
    await client.patch("/api/admin/settings/site_upload", json={"max_files": 2}, headers=as_member(admin))
    source = " ".join(f"![그림](attachment:{i})" for i in (1, 2, 3))
    res = await _save(client, admin, lid, 1, {"top": [{"type": "text", "config": {"source": source}}]})
    assert res.status_code == 422 and "2개까지" in res.json()["errors"][0]["message"]
