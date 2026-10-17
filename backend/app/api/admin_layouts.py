"""틀 관리 API — 홈블록 설계도 §7. 운영자 전용(site.design, U-3)."""

from fastapi import APIRouter, Depends, Header
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.scope import StaffScope
from app.api.admin_boards import admin_scope
from app.blocks import layouts
from app.core import rate_limit
from app.core.if_match import expected_version
from app.core.invalidation import tags_for
from app.db.session import SessionLocal, get_db

router = APIRouter(prefix="/admin")


def _detail(body: dict, status: int = 200, *, invalidate: bool = True) -> JSONResponse:
    if invalidate:
        body = body | {"invalidate": tags_for("layout.updated", layout_id=body["id"]).as_dict()}
    return JSONResponse(jsonable_encoder(body), status_code=status, headers={"ETag": f'"{body["version"]}"'})


async def _limit(scope: StaffScope) -> None:
    await rate_limit.hit("site.design", f"m:{scope.viewer.member_id}")


@router.get("/layouts")
async def list_layouts(scope: StaffScope = Depends(admin_scope), db: AsyncSession = Depends(get_db)):
    return jsonable_encoder(await layouts.list_layouts(db))


@router.post("/layouts", status_code=201)
async def create_layout(body: layouts.LayoutCreate, scope: StaffScope = Depends(admin_scope)):
    await _limit(scope)
    async with SessionLocal() as db, db.begin():
        out = await layouts.create_layout(db, scope.viewer, body)
    return _detail(out, 201)


@router.get("/layouts/{layout_id}")
async def get_layout(layout_id: int, scope: StaffScope = Depends(admin_scope), db: AsyncSession = Depends(get_db)):
    return _detail(await layouts.layout_detail(db, layout_id), invalidate=False)


@router.put("/layouts/{layout_id}")
async def save_layout(
    layout_id: int,
    body: layouts.LayoutSave,
    if_match: str | None = Header(None, alias="If-Match"),
    scope: StaffScope = Depends(admin_scope),
):
    """이름·블록 트리 통째 저장(§4.6) — 버전이 다르면 412 + 지금 ETag"""
    expected = expected_version(if_match, "틀")
    await _limit(scope)
    async with SessionLocal() as db, db.begin():
        out = await layouts.save_layout(db, scope.viewer, layout_id, body, expected)
    return _detail(out)


@router.delete("/layouts/{layout_id}")
async def delete_layout(layout_id: int, scope: StaffScope = Depends(admin_scope)):
    await _limit(scope)
    async with SessionLocal() as db, db.begin():
        await layouts.delete_layout(db, scope.viewer, layout_id)
    tags = tags_for("layout.updated", layout_id=layout_id)
    return {"deleted": layout_id, "invalidate": tags.as_dict()}


@router.post("/layouts/{layout_id}/default")
async def set_default(layout_id: int, scope: StaffScope = Depends(admin_scope)):
    """기본 틀 바꾸기 — 대응이 없는 화면 종류·틀을 고르지 않은 게시판·페이지가 모두 바뀐다(태그 layouts:bindings)"""
    await _limit(scope)
    async with SessionLocal() as db, db.begin():
        await layouts.set_default(db, scope.viewer, layout_id)
    return {"default": layout_id, "invalidate": tags_for("layouts.bindings").as_dict()}


@router.put("/layout-bindings")
async def save_bindings(body: layouts.BindingsSave, scope: StaffScope = Depends(admin_scope)):
    await _limit(scope)
    async with SessionLocal() as db, db.begin():
        bindings = await layouts.save_bindings(db, scope.viewer, body)
    return {"bindings": bindings, "invalidate": tags_for("layouts.bindings").as_dict()}
