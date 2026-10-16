"""인증 API — 인증 설계도 §5. 모든 쓰기는 Next Server Action → FastAPI(내부 비밀). 응답은 Cache-Control: private, no-store."""

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import login as service
from app.auth import sessions
from app.auth.viewer import SESSION_HEADER, Viewer, get_viewer
from app.core.client_ip import client_ip
from app.core.problems import Problem
from app.db.session import get_db

router = APIRouter()

DEVICE_HEADER = "X-Device"
NO_STORE = "private, no-store"


class LoginBody(BaseModel):
    # 형식 검사는 하지 않는다 — 형식이 틀린 이메일도 같은 실패 응답이어야 한다(계정 열거)
    email: str = Field(max_length=320)
    password: str = Field(max_length=1024)
    persistent: bool = False
    user_agent: str | None = Field(default=None, max_length=1000)  # 브라우저의 것(Next 가 전한다) — 기기 목록 표시용


class ConsentBody(BaseModel):
    consent_token: str = Field(max_length=500)
    user_agent: str | None = Field(default=None, max_length=1000)


@router.post("/auth/login")
async def login(body: LoginBody, request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> dict:
    response.headers["Cache-Control"] = NO_STORE
    result = await service.login(
        db,
        email=body.email,
        password=body.password,
        persistent=body.persistent,
        ip=client_ip(request),
        session_token=request.headers.get(SESSION_HEADER),
        device_token=request.headers.get(DEVICE_HEADER),
        user_agent=body.user_agent,
    )
    await db.commit()
    return result


@router.post("/auth/privacy-consent")
async def privacy_consent(body: ConsentBody, response: Response, db: AsyncSession = Depends(get_db)) -> dict:
    response.headers["Cache-Control"] = NO_STORE
    result = await service.consent(db, token=body.consent_token, user_agent=body.user_agent)
    await db.commit()
    return result


@router.post("/auth/logout", status_code=204)
async def logout(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    """이 기기 — 세션 폐기(기기 쿠키는 Next 가 남긴다). 세션이 없어도 성공"""
    token = request.headers.get(SESSION_HEADER)
    if token:
        await sessions.revoke_token(db, token)
        await db.commit()
    return Response(status_code=204, headers={"Cache-Control": NO_STORE})


@router.post("/auth/logout-all", status_code=204)
async def logout_all(viewer: Viewer = Depends(get_viewer), db: AsyncSession = Depends(get_db)) -> Response:
    if viewer.member_id is None or viewer.session_id is None:
        raise Problem(401, "login_required", "로그인이 필요합니다")
    await sessions.revoke_all(db, viewer.member_id)
    await db.commit()
    return Response(status_code=204, headers={"Cache-Control": NO_STORE})


@router.get("/privacy-notices/current")
async def current_notice(response: Response, db: AsyncSession = Depends(get_db)) -> dict:
    notice = await service.latest_notice(db)
    if notice is None:
        raise Problem(404, "no_privacy_notice", "게시된 개인정보 고지가 없습니다")
    response.headers["Cache-Control"] = NO_STORE
    return {
        "version": notice.version,
        "body": notice.body,
        "published_at": notice.published_at.isoformat() if notice.published_at else None,
        "requires_reconsent": notice.requires_reconsent,
    }
