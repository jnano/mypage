"""블록 그림의 공개 여부 맞추기 — 홈블록 설계도 §4.7·§5.3·§11.

공개 저장소(/media, nginx 가 직접 내준다)의 파일은 판정 없이 나가므로, 저장소 위치가 곧 권한이다(본 §12.1).
블록이 비회원에게 보이고(block_view(GUEST)) 주인도 공개(틀, 또는 게시 ∧ 열람 등급 0 인 페이지)면 공개, 아니면 비공개.
좁히는 쪽 먼저: 비공개로 내리는 표시는 저장 트랜잭션 안에서 바로, 파일 이동은 작업자(attach.reconcile_block)가.
공개로 올리는 것은 썸네일이 준비된 그림만, 작업자가 옮긴 뒤 주인 태그를 즉시 만료한다(묶음 응답이 옛 주소를 들고 있지 않게).
"""

from collections.abc import Iterable
from types import SimpleNamespace
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.auth.viewer import GUEST
from app.core import outbox
from app.models import Attachment, Block, Page
from app.permissions import block_view

PARENT = aliased(Block, name="parent")
ROW_COLUMNS = (
    Attachment.id, Attachment.block_id, Attachment.storage_key, Attachment.visibility, Attachment.thumbs_ready,
    Block.is_active, Block.audience, Block.min_level, Block.layout_id, Block.page_id,
    Page.status.label("page_status"), Page.view_level.label("page_view_level"),
    PARENT.id.label("parent_id"), PARENT.is_active.label("p_active"), PARENT.audience.label("p_audience"),
    PARENT.min_level.label("p_min_level"),
)  # fmt: skip


def desired(row: Any) -> str:
    owner_public = row.layout_id is not None or (row.page_status == "published" and row.page_view_level == 0)
    parent_public = row.parent_id is None or block_view(GUEST, SimpleNamespace(is_active=row.p_active, audience=row.p_audience, min_level=row.p_min_level))
    return "public" if owner_public and parent_public and block_view(GUEST, row) else "private"


async def load(db: AsyncSession, block_ids: Iterable[int]) -> list[Any]:
    ids = sorted(set(block_ids))
    if not ids:
        return []
    return list(
        await db.execute(
            select(*ROW_COLUMNS)  # post-clause: exempt — 첨부·블록 칸(글 아님)
            .join(Block, Block.id == Attachment.block_id)
            .outerjoin(Page, Page.id == Block.page_id)
            .outerjoin(PARENT, PARENT.id == Block.parent_id)
            .where(Attachment.block_id.in_(ids))
        )
    )


async def reconcile(db: AsyncSession, block_ids: Iterable[int]) -> None:
    """트랜잭션 안: 비공개여야 할 그림은 바로 비공개로 표시, 옮길 파일이 있을 수 있으면 작업자에게"""
    rows = await load(db, block_ids)
    if not rows:
        return
    demote = [r.id for r in rows if r.visibility == "public" and desired(r) == "private"]
    if demote:
        await db.execute(update(Attachment).where(Attachment.id.in_(demote)).values(visibility="private"))
    await outbox.enqueue(db, [outbox.Event("attach.reconcile_block", {"block_ids": sorted({r.block_id for r in rows})})])


async def release(db: AsyncSession, attachment_ids: Iterable[int]) -> None:
    """블록에서 떨어져 임시가 된 그림(블록·틀 삭제, 설정에서 뺌) — 24시간 뒤 정리될 때까지 공개 저장소에 남지 않게
    바로 비공개로 표시하고 파일은 작업자가 옮긴다(좁히는 쪽 먼저)"""
    ids = sorted(set(attachment_ids))
    if not ids:
        return
    public = list(
        (await db.execute(update(Attachment).where(Attachment.id.in_(ids), Attachment.visibility == "public").values(visibility="private").returning(Attachment.id))).scalars()
    )
    if public:
        await outbox.enqueue(db, [outbox.Event("attach.reconcile_block", {"block_ids": [], "released_ids": public})])
