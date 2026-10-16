"""회원 관리(가입 대기)·개인정보 고지 판 API — 인증 설계도 §5. 운영자 전용. 응답은 개인 정보라 no-store."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.scope import StaffScope
from app.api.admin_boards import admin_scope
from app.auth import members, notices
from app.db.session import get_db

router = APIRouter(prefix="/admin")

NO_STORE = "private, no-store"


@router.get("/members")
async def list_members(
    response: Response,
    status: Literal["pending"] = Query("pending"),
    scope: StaffScope = Depends(admin_scope),
    db: AsyncSession = Depends(get_db),
):
    """가입 대기열(§4.2). 활동 회원 목록은 회원 관리 화면 단계(§11-6)에서 더한다"""
    response.headers["Cache-Control"] = NO_STORE
    return {"status": status, "items": await members.list_pending(db)}


class ApproveBody(BaseModel):
    display_name: str | None = Field(default=None, max_length=200)  # 고쳐서 승인할 때만


@router.post("/members/{member_id}/approve")
async def approve(
    member_id: int, body: ApproveBody, scope: StaffScope = Depends(admin_scope), db: AsyncSession = Depends(get_db)
):
    result = await members.approve(db, scope.viewer, member_id, body.display_name)
    await db.commit()
    return result


class RejectBody(BaseModel):
    ids: Annotated[list[Annotated[int, Field(gt=0)]], Field(min_length=1, max_length=200)]
    reason: str | None = Field(default=None, max_length=500)


@router.post("/members/reject")
async def reject(body: RejectBody, scope: StaffScope = Depends(admin_scope), db: AsyncSession = Depends(get_db)):
    n = await members.reject(db, scope.viewer, body.ids, body.reason)
    await db.commit()
    return {"rejected": n}


@router.get("/privacy-notices")
async def list_notices(response: Response, scope: StaffScope = Depends(admin_scope), db: AsyncSession = Depends(get_db)):
    response.headers["Cache-Control"] = NO_STORE
    return {"items": await notices.list_notices(db)}


@router.post("/privacy-notices", status_code=201)
async def create_notice(
    body: notices.NoticeDraft, scope: StaffScope = Depends(admin_scope), db: AsyncSession = Depends(get_db)
):
    result = await notices.create_draft(db, scope.viewer, body)
    await db.commit()
    return result


@router.patch("/privacy-notices/{version}")
async def update_notice(
    version: str, body: notices.NoticeUpdate, scope: StaffScope = Depends(admin_scope), db: AsyncSession = Depends(get_db)
):
    result = await notices.update_draft(db, scope.viewer, version, body)
    await db.commit()
    return result


@router.post("/privacy-notices/{version}/publish")
async def publish_notice(version: str, scope: StaffScope = Depends(admin_scope), db: AsyncSession = Depends(get_db)):
    result = await notices.publish(db, scope.viewer, version)
    await db.commit()
    return result


