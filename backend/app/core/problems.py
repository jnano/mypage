"""오류 응답 — RFC 9457 application/problem+json. 모든 API 가 이 모듈 하나를 쓴다(§3.1-6).

확장 칸: code(기계가 읽는 오류 코드), errors([{field, message}]).
"""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.validation_messages import ko_message

MEDIA_TYPE = "application/problem+json"


class Problem(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        title: str,
        detail: str | None = None,
        errors: list[dict[str, str]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail
        self.errors = errors
        self.headers = headers
        super().__init__(title)


def problem_response(
    status: int,
    code: str,
    title: str,
    detail: str | None = None,
    errors: list[dict[str, str]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {"type": "about:blank", "title": title, "status": status, "code": code}
    if detail is not None:
        body["detail"] = detail
    if errors:
        body["errors"] = errors
    return JSONResponse(body, status_code=status, media_type=MEDIA_TYPE, headers=headers)


async def _on_problem(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, Problem)
    return problem_response(exc.status, exc.code, exc.title, exc.detail, exc.errors, exc.headers)


async def _on_http_exception(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    detail = exc.detail if isinstance(exc.detail, str) else None
    return problem_response(
        exc.status_code, f"http_{exc.status_code}", detail or "오류", headers=exc.headers
    )


async def _on_validation_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors = [
        {"field": ".".join(str(p) for p in e["loc"]), "message": ko_message(e)} for e in exc.errors()
    ]
    return problem_response(422, "validation_error", "입력값이 올바르지 않습니다", errors=errors)


def install(app: FastAPI) -> None:
    app.add_exception_handler(Problem, _on_problem)
    app.add_exception_handler(StarletteHTTPException, _on_http_exception)
    app.add_exception_handler(RequestValidationError, _on_validation_error)
