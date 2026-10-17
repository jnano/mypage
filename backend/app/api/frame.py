"""틀 묶음 공개 API — 홈블록 설계도 §5.2·§5.5·§7. 언제나 비회원 기준(보는 사람을 읽지 않는다 — B-2)."""

from fastapi import APIRouter, Depends, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy.ext.asyncio import AsyncSession

from app.blocks.frame import frame_bundle
from app.blocks.routes import ROUTE_CLASSES
from app.core.problems import Problem
from app.db.session import get_db

router = APIRouter()


@router.get("/frame")
async def frame(
    board: str | None = Query(None, max_length=100),
    route: str | None = Query(None, max_length=10),
    db: AsyncSession = Depends(get_db),
):
    """board(게시판 slug) / route(화면 종류) 중 하나, 둘 다 없으면 기본 틀. 사용자 페이지(path)는 걸음 6.
    응답의 cache.tags 로 Next 가 공개 캐시를 단다. 틀이 없으면 layout: null(화면이 대체 틀을 쓴다)."""
    if board is not None and route is not None:
        raise Problem(422, "validation_error", "board 와 route 중 하나만 보냅니다")
    if route is not None and route not in ROUTE_CLASSES:
        raise Problem(422, "validation_error", "없는 화면 종류입니다", errors=[{"field": "route", "message": "board·search·member·auth"}])
    return jsonable_encoder(await frame_bundle(db, board_slug=board, route=route))
