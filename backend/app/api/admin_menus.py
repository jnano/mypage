"""메뉴 관리 API — 홈블록 설계도 §7. 운영자 전용(site.design, U-3)."""

from fastapi import APIRouter, Depends, Header
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.scope import StaffScope
from app.api.admin_boards import admin_scope
from app.blocks import menus
from app.core import rate_limit
from app.core.if_match import expected_version
from app.core.invalidation import tags_for
from app.db.session import SessionLocal, get_db

router = APIRouter(prefix="/admin")


def _saved(body: dict, status: int = 200) -> JSONResponse:
    out = body | {"invalidate": tags_for("menu.updated", menu_id=body["id"]).as_dict()}
    return JSONResponse(jsonable_encoder(out), status_code=status, headers={"ETag": f'"{body["version"]}"'})


@router.get("/menus")
async def list_menus(scope: StaffScope = Depends(admin_scope), db: AsyncSession = Depends(get_db)):
    return {"menus": await menus.list_menus(db)}


@router.post("/menus", status_code=201)
async def create_menu(body: menus.MenuCreate, scope: StaffScope = Depends(admin_scope)):
    await rate_limit.hit("site.design", f"m:{scope.viewer.member_id}")
    async with SessionLocal() as db, db.begin():
        out = await menus.create_menu(db, scope.viewer, body)
    return _saved(out, 201)


@router.get("/menus/{menu_id}")
async def get_menu(menu_id: int, scope: StaffScope = Depends(admin_scope), db: AsyncSession = Depends(get_db)):
    out = await menus.menu_detail(db, menu_id)
    return JSONResponse(jsonable_encoder(out), headers={"ETag": f'"{out["version"]}"'})


@router.put("/menus/{menu_id}")
async def save_menu(
    menu_id: int,
    body: menus.MenuSave,
    if_match: str | None = Header(None, alias="If-Match"),
    scope: StaffScope = Depends(admin_scope),
):
    """항목 트리 통째 저장(§4.6) — 버전이 다르면 412 + 지금 ETag"""
    expected = expected_version(if_match, "메뉴")
    await rate_limit.hit("site.design", f"m:{scope.viewer.member_id}")
    async with SessionLocal() as db, db.begin():
        out = await menus.save_menu(db, scope.viewer, menu_id, body, expected)
    return _saved(out)


@router.delete("/menus/{menu_id}")
async def delete_menu(menu_id: int, scope: StaffScope = Depends(admin_scope)):
    await rate_limit.hit("site.design", f"m:{scope.viewer.member_id}")
    async with SessionLocal() as db, db.begin():
        await menus.delete_menu(db, scope.viewer, menu_id)
    return {"deleted": menu_id, "invalidate": tags_for("menu.updated", menu_id=menu_id).as_dict()}
