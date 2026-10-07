from fastapi import FastAPI

from app.api import health
from app.core.config import settings

app = FastAPI(title=settings.app_name, debug=settings.debug)

# 모든 API 는 /api 아래에 둔다 — 프론트엔드가 /api/* 를 그대로 프록시한다
app.include_router(health.router, prefix="/api")
