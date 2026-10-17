"""블록 편집 보조 API — 홈블록 설계도 §7·§8. 운영자 전용(site.design, U-3).

블록 종류(설정 폼의 형식), 저장 전 미리보기, 끊긴 참조 목록. 아무것도 저장하지 않는다.
"""

from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.scope import StaffScope
from app.api.admin_boards import admin_scope
from app.blocks import frame, layouts, schema, tree
from app.blocks.dangling import dangling
from app.core import rate_limit
from app.db.session import get_db

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


@router.post("/blocks/preview")
async def preview(body: PreviewIn, scope: StaffScope = Depends(admin_scope), db: AsyncSession = Depends(get_db)):
    """저장 전 트리를 그릴 모양으로(§8 '저장 전 모습을 보고 저장'). 검증은 저장과 같다(422 의 errors[].field 도 같은 꼴)"""
    await rate_limit.hit("blocks.preview", f"m:{scope.viewer.member_id}")
    if body.owner == "layout":
        groups, path = layouts.region_groups(body.regions), "regions"
    else:
        groups, path = [(None, body.blocks)], "blocks"
    try:
        flat = tree.validate_tree(body.owner, groups, path)
    except tree.TreeErrors as e:
        raise tree.problem(e.errors) from None
    return jsonable_encoder(await frame.preview(db, scope.viewer, flat, as_member=body.as_member))


@router.get("/blocks/dangling")
async def dangling_refs(scope: StaffScope = Depends(admin_scope), db: AsyncSession = Depends(get_db)):
    """끊긴 참조(§4.4 읽는 쪽 3) — 지워진 게시판·페이지·메뉴·그림을 가리키는 블록, 형식이 맞지 않는 블록, 예약 주소와 겹친 페이지"""
    return jsonable_encoder(await dangling(db))
