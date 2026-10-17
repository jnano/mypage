"""게시판 화면 묶음 응답·글 작성 — 설계도 §3.6, §6. 형식(일반·갤러리·한 줄…)별 경로는 없다."""

import math
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.viewer import Viewer, get_viewer
from app.core.problems import Problem
from app.db.session import get_db
from app.permissions import can, load_board_role
from app.core.client_ip import client_ip
from app.posts import guest, present, queries, service
from app.posts.schemas import GuestPostCreate, PostCreate

router = APIRouter()


@router.get("/boards/{slug}/page")
async def board_page(
    request: Request,
    slug: str,
    page: int = Query(1, ge=1),
    category: int | None = Query(None, gt=0),
    view: str | None = None,
    archived: bool = False,
    sort: Literal["latest"] = "latest",  # views·likes·comments 는 측정(§15) 뒤에 연다
    viewer: Viewer = Depends(get_viewer),
    db: AsyncSession = Depends(get_db),
):
    if page > queries.MAX_PAGE:
        raise Problem(
            400, "page_out_of_range", f"{queries.MAX_PAGE}쪽까지만 볼 수 있습니다",
            detail=f"max_page={queries.MAX_PAGE}",
        )  # fmt: skip
    board = await queries.find_board(db, slug)
    if board is None:
        if moved := await queries.find_moved_slug(db, slug):
            query = f"?{request.url.query}" if request.url.query else ""
            return RedirectResponse(f"/api/boards/{moved}/page{query}", status_code=308)
        raise Problem(404, "board_not_found", "게시판을 찾을 수 없습니다")

    role = await load_board_role(db, viewer, board.id)
    if not can(viewer, role, "board.list", board):
        if not board.is_active:
            raise Problem(404, "board_not_found", "게시판을 찾을 수 없습니다")
        raise Problem(403, "board_forbidden", "이 게시판을 볼 권한이 없습니다")

    categories = await queries.list_categories(db, board.id)
    if category is not None and category not in {c.id for c in categories}:
        raise Problem(404, "category_not_found", "카테고리를 찾을 수 없습니다")

    per_page = board.posts_per_page
    result = await queries.list_board_posts(
        db, viewer, role, board, page=page, per_page=per_page, category_id=category, archived=archived
    )
    has_restricted = await queries.has_restricted_posts(db, board.id)
    now = datetime.now(UTC)
    views = board.display.get("views") or ["list"]
    return {
        "board": present.board_summary(board),
        "categories": [{"id": c.id, "name": c.name} for c in categories],
        "view": view if view in views else board.display.get("default_view", views[0]),
        "pinned": [present.list_row(viewer, role, r, now) for r in result.pinned],
        "posts": [present.list_row(viewer, role, r, now) for r in result.rows],
        "page": {
            "page": page,
            "per_page": per_page,
            "total": result.total,
            "total_capped": result.total_capped,
            "last_page": max(1, math.ceil(result.total / per_page)),
            "category": category,
            "archived": archived,
            "sort": sort,
        },
        # 쪽 단위 캐시 판정용(§3.3): 보는 사람에 따라 달라지는 공개 글이 이 게시판에 있는지
        "cache": {"tags": [f"board:{board.slug}"], "has_restricted_posts": has_restricted},
    }


@router.post("/boards/{slug}/posts", status_code=201)
async def create_post(
    slug: str,
    body: PostCreate | GuestPostCreate,
    request: Request,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    viewer: Viewer = Depends(get_viewer),
):
    """회원 글과 비회원 글(§6.3)이 같은 경로 — 비회원 칸(이름·비밀번호·폼·보안 문자)이 있으면 비회원 글.
    비회원 글은 멱등 키를 쓰지 않는다(보안 문자가 한 번만이라 같은 제출이 두 번 들어가지 않는다)."""
    if isinstance(body, GuestPostCreate):
        if viewer.member_id is not None:
            raise Problem(422, "validation_error", "로그인한 회원은 비회원 칸을 보낼 수 없습니다")
        result = await guest.create(slug, body, client_ip(request))
    else:
        result = await service.create_post(viewer, slug, body, idempotency_key)
    return JSONResponse(result.body, status_code=result.status_code, headers=result.headers)


@router.get("/boards/{slug}/guest-form")
async def guest_form(slug: str, viewer: Viewer = Depends(get_viewer), db: AsyncSession = Depends(get_db)):
    """비회원 글쓰기 화면의 묶음 응답(§6.3) — 폼 토큰·보안 문자·정책·게시판. 토큰이 들어 있어 캐시하지 않는다"""
    if viewer.member_id is not None:
        raise Problem(409, "already_member", "로그인한 회원은 회원 글쓰기를 씁니다")
    return JSONResponse(await guest.guest_form(db, slug), headers={"Cache-Control": "no-store"})
