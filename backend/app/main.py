import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from app.api import admin, admin_boards, admin_moderation, admin_posts, attachments, boards, comments, editor, health, me, notifications, posts, reports, search
from app.core import csrf, problems, timing
from app.core.config import settings
from app.db.session import engine
from app.files import storage

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if settings.dev_viewer_header:
        logger.warning("개발용 Viewer 헤더(X-Dev-Member)가 켜져 있습니다 — ENV=dev 전용")
    yield
    await engine.dispose()


app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)
problems.install(app)
csrf.install(app)
if settings.server_timing:
    timing.install(app)

# 모든 API 는 /api 아래에 둔다 — 프론트엔드가 /api/* 를 그대로 프록시한다
app.include_router(health.router, prefix="/api")
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
app.include_router(reports.router, prefix="/api")

# 공개 저장소 /media — 배포에서는 nginx 가 직접 내준다(§12.2). 개발(FILE_SENDER=stream)에서만 FastAPI 가 내준다
if settings.file_sender == "stream":
    app.mount("/media", StaticFiles(directory=storage.root("public"), check_dir=False), name="media")


@app.middleware("http")
async def nosniff_media(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/media/"):
        response.headers["X-Content-Type-Options"] = "nosniff"
    return response
