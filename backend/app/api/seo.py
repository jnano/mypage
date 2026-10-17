"""SEO 공개 API — 설계도 §10. 모두 비회원 기준(쿠키 없음 → 공개 캐시). 캐시 태그는 응답의 cache.tags."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin import settings as site_settings
from app.blocks import pages
from app.core.problems import Problem
from app.db.session import get_db
from app.seo import queries

router = APIRouter()


@router.get("/site")
async def site(db: AsyncSession = Depends(get_db)):
    """사이트 공개 설정 — 이름·주소·설명·검색엔진 확인 값·색인 여부, 등급 이름표, 대체 틀의 게시판 메뉴(홈블록 §3.6)."""
    seo = await site_settings.load(db, "seo")
    levels = await site_settings.load(db, "levels")
    return {
        "seo": seo.model_dump(),
        "levels": levels.model_dump(),
        "menu_boards": await queries.menu_boards(db),
        "cache": {"tags": ["settings:seo", "settings:levels", "boards:structure"]},
    }


@router.get("/seo/sitemap")
async def sitemap_index(db: AsyncSession = Depends(get_db)):
    # 사용자 페이지(홈블록 §15 — 본 §10 에 더함). 페이지 게시·주소 변경은 page.updated 가 pages:paths(즉시)·sitemap(max) 을 만료한다
    return await queries.sitemap_index(db) | {"pages": await pages.sitemap_pages(db), "cache": {"tags": ["sitemap", "boards:structure", "pages:paths"]}}


@router.get("/seo/sitemap/posts")
async def sitemap_posts(part: int = Query(0, ge=0, le=10_000), db: AsyncSession = Depends(get_db)):
    return {"items": await queries.sitemap_posts(db, part), "cache": {"tags": ["sitemap"]}}


@router.get("/seo/feed")
async def feed(board: str | None = Query(None, max_length=100), db: AsyncSession = Depends(get_db)):
    result = await queries.feed(db, board)
    if result is None:
        raise Problem(404, "feed_not_found", "피드가 없는 게시판입니다")
    tags = [f"feed:{board}", f"board:{board}"] if board else ["recent:posts"]
    return result | {"cache": {"tags": tags}}
