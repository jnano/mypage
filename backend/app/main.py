import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import health
from app.core import problems
from app.core.config import settings
from app.db.session import engine

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if settings.dev_viewer_header:
        logger.warning("개발용 Viewer 헤더(X-Dev-Member)가 켜져 있습니다 — ENV=dev 전용")
    yield
    await engine.dispose()


app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)
problems.install(app)

# 모든 API 는 /api 아래에 둔다 — 프론트엔드가 /api/* 를 그대로 프록시한다
app.include_router(health.router, prefix="/api")
