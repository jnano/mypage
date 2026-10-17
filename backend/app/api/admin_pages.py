"""페이지 관리 API — 홈블록 설계도 §7. 운영자 전용(site.design, U-3)."""

from fastapi import APIRouter, Depends, Header
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.scope import StaffScope
from app.api.admin_boards import admin_scope
from app.blocks import pages
from app.core import rate_limit
from app.core.if_match import expected_version
from app.core.invalidation import tags_for
from app.db.session import SessionLocal, get_db

router = APIRouter(prefix="/admin")


def _detail(body: dict, status: int = 200, *, invalidate: bool = True) -> JSONResponse:
    if invalidate:
        body = body | {"invalidate": tags_for("page.updated", page_id=body["id"]).as_dict()}
    return JSONResponse(jsonable_encoder(body), status_code=status, headers={"ETag": f'"{body["version"]}"'})


async def _limit(scope: StaffScope) -> None:
    await rate_limit.hit("site.design", f"m:{scope.viewer.member_id}")


@router.get("/pages")
async def list_pages(scope: StaffScope = Depends(admin_scope), db: AsyncSession = Depends(get_db)):
    return jsonable_encoder({"pages": await pages.list_pages(db), "reserved_conflicts": await pages.reserved_conflicts(db)})


@router.post("/pages", status_code=201)
async def create_page(body: pages.PageCreate, scope: StaffScope = Depends(admin_scope)):
    """초안으로 만든다 — 게시는 따로(publish)"""
    await _limit(scope)
    async with SessionLocal() as db, db.begin():
        out = await pages.create_page(db, scope.viewer, body)
    return _detail(out, 201)


@router.get("/pages/{page_id}")
async def get_page(page_id: int, scope: StaffScope = Depends(admin_scope), db: AsyncSession = Depends(get_db)):
    return _detail(await pages.page_detail(db, page_id), invalidate=False)


@router.put("/pages/{page_id}")
async def save_page(
    page_id: int,
    body: pages.PageSave,
    if_match: str | None = Header(None, alias="If-Match"),
    scope: StaffScope = Depends(admin_scope),
):
    """속성·본문 블록 트리 통째 저장(§4.6) — 버전이 다르면 412 + 지금 ETag"""
    expected = expected_version(if_match, "페이지")
    await _limit(scope)
    async with SessionLocal() as db, db.begin():
        out = await pages.save_page(db, scope.viewer, page_id, body, expected)
    return _detail(out)


@router.post("/pages/{page_id}/publish")
async def publish(page_id: int, scope: StaffScope = Depends(admin_scope)):
    await _limit(scope)
    async with SessionLocal() as db, db.begin():
        out = await pages.set_status(db, scope.viewer, page_id, True)
    return _detail(out)


@router.post("/pages/{page_id}/unpublish")
async def unpublish(page_id: int, scope: StaffScope = Depends(admin_scope)):
    await _limit(scope)
    async with SessionLocal() as db, db.begin():
        out = await pages.set_status(db, scope.viewer, page_id, False)
    return _detail(out)


@router.delete("/pages/{page_id}")
async def delete_page(page_id: int, scope: StaffScope = Depends(admin_scope)):
    await _limit(scope)
    async with SessionLocal() as db, db.begin():
        await pages.delete_page(db, scope.viewer, page_id)
    return {"deleted": page_id, "invalidate": tags_for("page.updated", page_id=page_id).as_dict()}
