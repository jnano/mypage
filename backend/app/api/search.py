"""검색 API — 설계도 §9. 결과는 캐시하지 않는다(검색어는 사용자가 마음대로 넣는 값)."""

from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.viewer import Viewer, get_viewer
from app.core import rate_limit
from app.core.problems import Problem
from app.db.session import get_db
from app.permissions import can, load_board_role
from app.posts import queries
from app.search.backend import COUNT_CAP, PER_PAGE, backend, parse_query

router = APIRouter()


@router.get("/search")
async def search(
    q: str = Query(..., max_length=1000),
    board: str | None = None,
    scope: Literal["all", "title"] = "all",
    page: int = Query(1, ge=1),
    viewer: Viewer = Depends(get_viewer),
    db: AsyncSession = Depends(get_db),
):
    board_id = None
    if board is not None:
        found = await queries.find_board(db, board)
        if found is None:
            raise Problem(404, "board_not_found", "게시판을 찾을 수 없습니다")
        role = await load_board_role(db, viewer, found.id)
        if not can(viewer, role, "board.list", found):
            raise Problem(403, "board_forbidden", "이 게시판을 볼 권한이 없습니다")
        board_id = found.id
    query = parse_query(q, board_id=board_id, scope=scope, page=page)
    if viewer.member_id is not None:
        await rate_limit.hit("search", f"m:{viewer.member_id}")

    result = await backend.search(db, viewer, query)
    body = {
        "q": query.text,
        "results": [
            {
                "id": r.id,
                "title": r.title,
                "author_name": r.author_name_snapshot,
                "published_at": r.published_at.isoformat() if r.published_at else None,
                "board": {"slug": r.board_slug, "name": r.board_name},
            }
            for r in result.rows
        ],
        "page": {
            "page": page,
            "per_page": PER_PAGE,
            "total": result.total,
            "total_capped": result.total_capped,
            "last_page": max(1, -(-result.total // PER_PAGE)),
            "max_total": COUNT_CAP,
        },
    }
    return JSONResponse(body, headers={"Cache-Control": "no-store"})


@router.get("/health/search")
async def search_health(db: AsyncSession = Depends(get_db)) -> dict:
    return await backend.healthcheck(db)
