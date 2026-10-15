"""쓰기 경계 — 설계도 §3.5, §6.

사용자 쓰기는 Next 서버(Server Action 또는 Route Handler)를 거친다. Next 서버만 아는 내부 비밀 헤더가 없는
상태 변경 요청은 거부한다. 그러면 브라우저가 rewrites(/api/*)로 FastAPI 쓰기 API 를 직접 부를 수 없고,
사용자 요청의 CSRF 는 Server Action 의 출처 검사(Origin ↔ Host)가 맡는다.
브라우저 직접 쓰기(업로드 등)도 Next Route Handler 를 거치게 하므로 허용 목록은 두지 않는다.
"""

import hmac

from fastapi import FastAPI, Request
from starlette.responses import Response

from app.core.config import settings
from app.core.problems import problem_response

HEADER = "X-Internal-Secret"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def is_internal(request: Request) -> bool:
    secret = settings.internal_api_secret
    given = request.headers.get(HEADER)
    return bool(secret) and given is not None and hmac.compare_digest(given.encode(), secret.encode())


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def require_internal_for_writes(request: Request, call_next) -> Response:
        if request.method not in SAFE_METHODS and not is_internal(request):
            return problem_response(
                403, "csrf_forbidden", "이 요청은 사이트 화면을 통해서만 보낼 수 있습니다"
            )
        return await call_next(request)
