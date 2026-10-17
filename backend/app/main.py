import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from app.api import account, admin, admin_boards, admin_members, admin_menus, admin_moderation, admin_posts, admin_site, attachments, auth, boards, comments, editor, health, me, notifications, posts, reports, search, seo
from app.core import csrf, problems, timing
from app.core.config import settings
from app.db.session import engine
from app.files import storage
from app.posts import view_buffer
from app.search import terms as search_terms

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if settings.dev_viewer_header:
        logger.warning("개발용 Viewer 헤더(X-Dev-Member)가 켜져 있습니다 — ENV=dev 전용")
    # 메모리 묶음을 비우는 배경 작업 — always 모드 조회수(§6.1)·검색어 집계(§9.1)
    flushers = [asyncio.create_task(view_buffer.run_forever()), asyncio.create_task(search_terms.run_forever())]
    yield
    for task in flushers:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    await view_buffer.flush()  # 정상 종료 때 남은 것
    await search_terms.flush()
    await engine.dispose()


def docs_urls(env: str) -> dict[str, str | None]:
    """FastAPI 기본 문서(/docs·/redoc·/openapi.json) — 운영(ENV=prod)에서는 끈다(설계도 §11).
    운영 백엔드는 127.0.0.1 에만 묶이고 nginx 가 이 경로를 넘기지 않아 바깥에서는 닿지 않지만, API 지도를 내보일 까닭이 없다."""
    on = env != "prod"
    return {"docs_url": "/docs" if on else None, "redoc_url": "/redoc" if on else None, "openapi_url": "/openapi.json" if on else None}


app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan, **docs_urls(settings.env))
problems.install(app)
csrf.install(app)
if settings.server_timing:
    timing.install(app)

# 모든 API 는 /api 아래에 둔다 — 프론트엔드가 /api/* 를 그대로 프록시한다
app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(account.router, prefix="/api")
app.include_router(boards.router, prefix="/api")
app.include_router(posts.router, prefix="/api")
app.include_router(comments.router, prefix="/api")
app.include_router(attachments.router, prefix="/api")
app.include_router(editor.router, prefix="/api")
app.include_router(me.router, prefix="/api")
app.include_router(notifications.router, prefix="/api")
app.include_router(search.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(admin_boards.router, prefix="/api")
app.include_router(admin_posts.router, prefix="/api")
app.include_router(admin_moderation.router, prefix="/api")
app.include_router(admin_site.router, prefix="/api")
app.include_router(admin_members.router, prefix="/api")
app.include_router(admin_menus.router, prefix="/api")
app.include_router(reports.router, prefix="/api")
app.include_router(seo.router, prefix="/api")

# 공개 저장소 /media — 배포에서는 nginx 가 직접 내준다(§12.2). 개발(FILE_SENDER=stream)에서만 FastAPI 가 내준다
if settings.file_sender == "stream":
    app.mount("/media", StaticFiles(directory=storage.root("public"), check_dir=False), name="media")


@app.middleware("http")
async def nosniff_media(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/media/"):
        response.headers["X-Content-Type-Options"] = "nosniff"
    return response
