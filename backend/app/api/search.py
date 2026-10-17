"""검색 API — 설계도 §9. 결과는 캐시하지 않는다(검색어는 사용자가 마음대로 넣는 값)."""

from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.viewer import Viewer, get_viewer
from app.admin import settings as site_settings
from app.admin.settings import SearchSettings
from app.core import rate_limit
from app.core.client_ip import client_ip
from app.core.problems import Problem
from app.db.session import get_db
from app.permissions import can, load_board_role
from app.posts import queries
from app.search import terms
from app.search.backend import COUNT_CAP, PER_PAGE, backend, parse_query

router = APIRouter()


@router.get("/search")
async def search(
    request: Request,
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
    # 회원은 회원 id, 비회원은 실제 IP(§6.3 — client_ip() 가 생겨 비회원도 센다. 검색어 집계의 30초 기억에도 상한이 생긴다)
    await rate_limit.hit("search", f"m:{viewer.member_id}" if viewer.member_id is not None else f"ip:{client_ip(request)}")

    result = await backend.search(db, viewer, query)
    if page == 1:  # 검색어 집계(§9.1) — 결과를 낸 첫 쪽만, 메모리에 넣고 끝
        terms.record(query.text, q, terms.searcher_of(viewer, client_ip(request)))
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


TERMS_TAGS = ("settings:search", "settings:spam")  # 금지어를 바꿔도 바로(검토 묶음C N-1)


@router.get("/search/terms")
async def search_terms(db: AsyncSession = Depends(get_db)):
    """인기·추천 검색어 묶음 응답(§9.1) — 공개 캐시(사람마다 다르지 않다). 태그는 거르기에 쓰는 설정 둘(검색 제외·금지어),
    집계로는 무효화하지 않는다"""
    search = await site_settings.load(db, "search")
    assert isinstance(search, SearchSettings)
    body = {"popular": await terms.popular(db, search), "recommended": search.recommended, "cache": {"tags": list(TERMS_TAGS)}}
    return JSONResponse(body)


@router.get("/health/search")
async def search_health(db: AsyncSession = Depends(get_db)) -> dict:
    return await backend.healthcheck(db)
