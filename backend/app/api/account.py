"""내 계정 API — 인증 설계도 §5 '내 계정'. 응답은 no-store. /me/* 의 id 경로는 본인 소유를 확인한다."""

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import account, levels
from app.auth.viewer import Viewer, get_viewer
from app.db.session import get_db

router = APIRouter()

NO_STORE = "private, no-store"


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=1024)
    new_password: str = Field(max_length=1024)


class Reauth(BaseModel):
    password: str = Field(max_length=1024)


@router.get("/me/account")
async def get_account(response: Response, viewer: Viewer = Depends(get_viewer), db: AsyncSession = Depends(get_db)):
    response.headers["Cache-Control"] = NO_STORE
    return await account.account(db, viewer)


@router.post("/me/password", status_code=204)
async def change_password(body: PasswordChange, viewer: Viewer = Depends(get_viewer), db: AsyncSession = Depends(get_db)):
    await account.change_password(db, viewer, body.current_password, body.new_password)
    await db.commit()
    return Response(status_code=204, headers={"Cache-Control": NO_STORE})


@router.get("/me/sessions")
async def list_sessions(response: Response, viewer: Viewer = Depends(get_viewer), db: AsyncSession = Depends(get_db)):
    response.headers["Cache-Control"] = NO_STORE
    return {"items": await account.list_sessions(db, viewer)}


@router.delete("/me/sessions/{session_id}", status_code=204)
async def revoke_session(session_id: int, viewer: Viewer = Depends(get_viewer), db: AsyncSession = Depends(get_db)):
    await account.revoke_session(db, viewer, session_id)
    await db.commit()
    return Response(status_code=204, headers={"Cache-Control": NO_STORE})


@router.post("/me/withdraw", status_code=204)
async def withdraw(body: Reauth, viewer: Viewer = Depends(get_viewer), db: AsyncSession = Depends(get_db)):
    await account.withdraw_self(db, viewer, body.password)
    await db.commit()
    return Response(status_code=204, headers={"Cache-Control": NO_STORE})


@router.get("/me/level-requests")
async def my_level_requests(response: Response, viewer: Viewer = Depends(get_viewer), db: AsyncSession = Depends(get_db)):
    response.headers["Cache-Control"] = NO_STORE
    return await levels.my_requests(db, viewer)


@router.post("/me/level-requests", status_code=201)
async def create_level_request(body: levels.LevelRequestBody, viewer: Viewer = Depends(get_viewer), db: AsyncSession = Depends(get_db)):
    result = await levels.create_request(db, viewer, body)
    await db.commit()
    return result


@router.delete("/me/level-requests/{request_id}", status_code=204)
async def cancel_level_request(request_id: int, viewer: Viewer = Depends(get_viewer), db: AsyncSession = Depends(get_db)):
    await levels.cancel_request(db, viewer, request_id)
    await db.commit()
    return Response(status_code=204, headers={"Cache-Control": NO_STORE})
