"""끊긴 참조 — 홈블록 설계도 §4.4(읽는 쪽 셋 중 3)·§11(G-04 '당사자에게 알린다').

블록 설정의 참조(게시판·페이지·메뉴·그림 id)는 JSONB 안이라 FK 가 없다. 대상이 지워지면 렌더는 건너뛰고(블록이 비면 그리지
않는다), 운영자는 여기서 목록으로 보고 고친다. 지금 형식으로 검증되지 않는 설정(형식이 바뀐 뒤 남은 행)도 함께 낸다 —
렌더가 경고 로그를 남기고 건너뛰는 것과 같은 행이다.

블록은 주인당 60 × (틀 + 페이지 ≤ 1,000)라 한 번에 읽는다. 운영자 화면에서만 부른다(쿼리 ≤ 5: 블록·페이지·게시판·메뉴·그림). 시간은 걸음 8 에서 상한 구성으로 잰다(M-8).
"""

from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.blocks import types as t
from app.blocks.routes import reserved
from app.blocks.tree import Refs, collect_refs
from app.core import outbox
from app.models import Attachment, Block, BlockHealth, Board, Layout, Menu, Page

# 끊긴 참조 수를 다시 세라는 사건(§4.9) — 블록·페이지·메뉴·게시판이 바뀌거나 지워지는 트랜잭션 안에서 넣는다(그 저장이 롤백되면 사건도 없다)
RECOUNT = "blocks.recount"


async def request_recount(db: AsyncSession) -> None:
    await outbox.enqueue(db, [outbox.Event(RECOUNT)])


async def dangling(db: AsyncSession) -> dict[str, Any]:
    rows = list(
        await db.execute(
            select(Block.id, Block.type, Block.config, Block.layout_id, Block.page_id, Layout.name.label("layout_name"), Page.path.label("page_path"))  # post-clause: exempt — 블록 칸(글 아님)
            .outerjoin(Layout, Layout.id == Block.layout_id)
            .outerjoin(Page, Page.id == Block.page_id)
            .order_by(Block.layout_id.nulls_last(), Block.page_id, Block.id)
        )
    )
    refs: dict[int, Refs] = {}
    invalid: set[int] = set()
    for row in rows:
        try:
            refs[row.id] = collect_refs(t.validate_config(row.type, row.config))
        except (ValidationError, t.UnknownBlockType):
            invalid.add(row.id)
    want = Refs()
    for x in refs.values():
        want.pages |= x.pages
        want.boards |= x.boards
        want.menus |= x.menus
    # 페이지는 한 번 — 참조 확인과 예약 주소 겹침이 같은 행을 쓴다(페이지 ≤ 1,000, 코드 검토 v15 N-2)
    all_pages = list(await db.execute(select(Page.id, Page.path)))
    have_pages = {r.id for r in all_pages}
    have_boards = set((await db.execute(select(Board.id).where(Board.id.in_(want.boards)))).scalars()) if want.boards else set()
    have_menus = set((await db.execute(select(Menu.id).where(Menu.id.in_(want.menus)))).scalars()) if want.menus else set()
    # 그림은 그 블록에 붙어 있어야 그려진다(§4.7 — block_id). 지워졌거나 떨어진 그림
    attached: set[tuple[int, int]] = set()
    if any(x.attachments for x in refs.values()):
        attached = {(r.block_id, r.id) for r in await db.execute(select(Attachment.block_id, Attachment.id).where(Attachment.block_id.in_(list(refs))))}  # post-clause: exempt — 첨부 칸(글 아님)

    out = []
    for row in rows:
        owner = {"kind": "layout", "id": row.layout_id, "name": row.layout_name} if row.layout_id else {"kind": "page", "id": row.page_id, "name": row.page_path}
        if row.id in invalid:
            out.append({"id": row.id, "type": row.type, "owner": owner, "invalid": True, "missing": {}})
            continue
        x = refs[row.id]
        missing = {
            "pages": sorted(x.pages - have_pages),
            "boards": sorted(x.boards - have_boards),
            "menus": sorted(x.menus - have_menus),
            "attachments": sorted(a for a in x.attachments if (row.id, a) not in attached),
        }
        missing = {k: v for k, v in missing.items() if v}
        if missing:
            out.append({"id": row.id, "type": row.type, "owner": owner, "invalid": False, "missing": missing})
    return {"blocks": out, "reserved_conflicts": [{"id": r.id, "path": r.path} for r in all_pages if reserved(r.path)]}


async def recount(db: AsyncSession) -> dict[str, int]:
    """작업자 — 지금 전체를 세어 block_health 한 행에(§4.9). 겹치면 나중 값(둘 다 그때의 전체)"""
    out = await dangling(db)
    values = {"broken_blocks": len(out["blocks"]), "reserved_pages": len(out["reserved_conflicts"])}
    stmt = insert(BlockHealth).values(id=1, **values)
    await db.execute(stmt.on_conflict_do_update(index_elements=[BlockHealth.id], set_=values | {"counted_at": func.now()}))
    return values
