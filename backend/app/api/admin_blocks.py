"""블록 편집 보조 API — 홈블록 설계도 §7·§8. 운영자 전용(site.design, U-3).

블록 종류(설정 폼의 형식), 저장 전 미리보기, 끊긴 참조 목록. 아무것도 저장하지 않는다.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.scope import StaffScope
from app.api.admin_boards import admin_scope
from app.blocks import frame, layouts, pages, schema, tree
from app.blocks.dangling import dangling
from app.core import rate_limit
from app.db.session import get_db
from app.models import Layout

router = APIRouter(prefix="/admin")


@router.get("/block-types")
async def block_types(scope: StaffScope = Depends(admin_scope)):
    """종류·설정 형식(JSON Schema + 이름·부품)·놓을 수 있는 곳·쓸 수 있음 — 관리 화면이 이것으로 폼을 만든다(§8)"""
    return schema.block_types()


class PreviewIn(BaseModel):
    """미리보기할 트리 — 틀이면 regions(영역 → 블록 목록), 페이지면 blocks(본문). 저장 본문과 같은 꼴"""

    model_config = ConfigDict(extra="forbid")

    owner: Literal["layout", "page"]
    regions: dict[str, list[tree.BlockIn]] = {}
    blocks: list[tree.BlockIn] = []
    as_member: bool = False  # 참이면 이 운영자 기준(회원 블록까지), 거짓이면 비회원이 보는 모습
    # 같은 화면에 함께 그려질 쪽 — 저장과 같은 이름표 검사(§10)를 미리보기에서도 하려고(코드 검토 v15 N-3 a).
    # 페이지면 그 페이지가 고른 틀(없으면 기본 틀), 틀이면 고치는 틀의 id(그 틀을 쓰는 페이지들과 대조, 없으면 새 틀)
    layout_id: Annotated[int, Field(ge=1)] | None = None


@router.post("/blocks/preview")
async def preview(body: PreviewIn, scope: StaffScope = Depends(admin_scope), db: AsyncSession = Depends(get_db)):
    """저장 전 트리를 그릴 모양으로(§8 '저장 전 모습을 보고 저장'). 검증은 저장과 같다(422 의 errors[].field 도 같은 꼴)"""
    await rate_limit.hit("blocks.preview", f"m:{scope.viewer.member_id}")
    if body.owner == "layout":
        groups, path = layouts.region_groups(body.regions), "regions"
    else:
        groups, path = [(None, body.blocks)], "blocks"
    taken = None
    if body.owner == "page":
        layout_id = await pages.layout_for(db, body.layout_id)
        taken = await tree.nav_labels(db, layout_ids=[layout_id] if layout_id else [])
    try:
        flat = tree.validate_tree(body.owner, groups, path, taken)
    except tree.TreeErrors as e:
        raise tree.problem(e.errors) from None
    if body.owner == "layout" and body.layout_id is not None and (layout := await db.get(Layout, body.layout_id)) is not None:
        if errors := await tree.page_conflicts(db, layout.id, layout.is_default, tree.names_in(flat)):
            raise tree.problem(errors)
    return jsonable_encoder(await frame.preview(db, scope.viewer, flat, as_member=body.as_member))


@router.get("/blocks/dangling")
async def dangling_refs(scope: StaffScope = Depends(admin_scope), db: AsyncSession = Depends(get_db)):
    """끊긴 참조(§4.4 읽는 쪽 3) — 지워진 게시판·페이지·메뉴·그림을 가리키는 블록, 형식이 맞지 않는 블록, 예약 주소와 겹친 페이지"""
    return jsonable_encoder(await dangling(db))
