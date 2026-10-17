"""틀 묶음 API — 홈블록 설계도 §5.2·§5.5·§6.2·§7. 공개 /api/frame 은 언제나 비회원 기준(보는 사람을 읽지 않는다 — B-2),
개인 /api/me/frame 은 열람 등급 페이지와 운영자의 초안 보기. 주소 집합 /api/pages/paths."""

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.viewer import Viewer, get_viewer
from app.blocks import pages
from app.blocks.frame import PageNotFound, frame_bundle, viewer_frame
from app.blocks.routes import ROUTE_CLASSES, is_page_path
from app.core import rate_limit
from app.core.problems import Problem
from app.db.session import get_db

router = APIRouter()


def _not_found(e: PageNotFound, prefix: str) -> Response:
    """없는 페이지 404, 옛 주소면 308 + 새 주소(게시판 slug 와 같은 방식 — 본 §14.5). Next 는 주소 집합으로 먼저 거르므로
    정상 흐름에서는 부르지 않는다(§5.5)"""
    if e.moved is not None:
        location = f"{prefix}?{urlencode({'path': e.moved})}"
        return JSONResponse({"moved": e.moved}, status_code=308, headers={"Location": location})
    raise Problem(404, "page_not_found", "페이지를 찾을 수 없습니다")


@router.get("/frame")
async def frame(
    board: str | None = Query(None, max_length=100),
    route: str | None = Query(None, max_length=10),
    path: str | None = Query(None, max_length=160),
    db: AsyncSession = Depends(get_db),
):
    """board(게시판 slug) / route(화면 종류) / path(사용자 페이지) 중 하나, 모두 없으면 기본 틀.
    응답의 cache.tags 로 Next 가 공개 캐시를 단다. 틀이 없으면 layout: null(화면이 대체 틀을 쓴다). 언제나 비회원 기준(B-2)."""
    if sum(x is not None for x in (board, route, path)) > 1:
        raise Problem(422, "validation_error", "board·route·path 중 하나만 보냅니다")
    if route is not None and route not in ROUTE_CLASSES:
        raise Problem(422, "validation_error", "없는 화면 종류입니다", errors=[{"field": "route", "message": "board·search·member·auth"}])
    if path is not None and not is_page_path(path):
        raise Problem(404, "page_not_found", "페이지를 찾을 수 없습니다")
    try:
        return jsonable_encoder(await frame_bundle(db, board_slug=board, route=route, path=path))
    except PageNotFound as e:
        return _not_found(e, "/api/frame")


@router.get("/me/frame")
async def me_frame(
    path: str = Query(..., max_length=160),
    draft: bool = False,
    viewer: Viewer = Depends(get_viewer),
    db: AsyncSession = Depends(get_db),
):
    """개인 틀 — 열람 등급 페이지(§6.2)와 운영자의 초안 보기(draft=1, §5.5). 보는 사람 기준, 캐시하지 않는다.
    초안 보기는 운영자 표시 쿠키로 들어오는 길이라 쿠키를 위조해 호출 수를 늘릴 수 있다 — 회원 단위 분당 60(frame.draft)"""
    if viewer.member_id is None:  # 쿠키는 있는데 세션이 만료·폐기 — 화면이 '볼 수 없음' 대신 다시 로그인으로 가르게(코드 검토 v13 N-2)
        raise Problem(404, "signed_out", "페이지를 찾을 수 없습니다")
    if not is_page_path(path):
        raise Problem(404, "page_not_found", "페이지를 찾을 수 없습니다")
    if draft:
        await rate_limit.hit("frame.draft", f"m:{viewer.member_id}")
    try:
        body = await viewer_frame(db, viewer, path, draft=draft)
    except PageNotFound as e:
        return _not_found(e, "/api/me/frame")
    return JSONResponse(jsonable_encoder(body), headers={"Cache-Control": "no-store"})


@router.get("/pages/paths")
async def page_paths(db: AsyncSession = Depends(get_db)):
    """주소 집합(§5.5) — 공개. Next 가 [[...path]] 의 주소를 FastAPI 를 부르기 전에 이것으로 거른다(B-1)"""
    return await pages.public_paths(db)
