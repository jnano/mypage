"""회원 관리(가입 대기)·개인정보 고지 판 API — 인증 설계도 §5. 운영자 전용. 응답은 개인 정보라 no-store."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.scope import StaffScope
from app.api.admin_boards import admin_scope
from app.admin import groups
from app.auth import account, member_admin, members, notices
from app.db.session import get_db

router = APIRouter(prefix="/admin")

NO_STORE = "private, no-store"


@router.get("/members")
async def list_members(
    response: Response,
    status: Literal["pending", "active", "withdrawn"] = Query("active"),
    q: str | None = Query(None, max_length=100),
    after: int | None = Query(None, gt=0),
    scope: StaffScope = Depends(admin_scope),
    db: AsyncSession = Depends(get_db),
):
    """회원 목록 — 가입 대기열(§4.2) 또는 활동·탈퇴 회원(이메일·표시 이름 검색, id 커서). 운영자만(이메일 포함)"""
    response.headers["Cache-Control"] = NO_STORE
    if status == "pending":
        return {"status": status, "items": await members.list_pending(db), "next_after": None}
    return {"status": status} | await member_admin.list_members(db, status=status, q=q, after_id=after)


@router.get("/members/{member_id}")
async def get_member(member_id: int, response: Response, scope: StaffScope = Depends(admin_scope), db: AsyncSession = Depends(get_db)):
    response.headers["Cache-Control"] = NO_STORE
    return await member_admin.member_detail(db, member_id)


@router.patch("/members/{member_id}")
async def patch_member(
    member_id: int, body: member_admin.MemberPatch, scope: StaffScope = Depends(admin_scope), db: AsyncSession = Depends(get_db)
):
    """레벨·표시 이름·이메일·운영자 지정. 이메일·운영자 지정은 운영자 본인 비밀번호(password) 재확인"""
    result = await member_admin.patch_member(db, scope.viewer, member_id, body)
    await db.commit()
    return result


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


class Reauth(BaseModel):
    password: str = Field(max_length=1024)  # 운영자 본인 비밀번호 재확인(§4.13)


class ForcedWithdraw(Reauth):
    reason: str = Field(max_length=500)

    @field_validator("reason")
    @classmethod
    def _reason(cls, v: str) -> str:
        if not v.strip():  # 사유 필수 — 공백만은 사유가 아니다(검토 v4 T-4)
            raise ValueError("사유를 적어 주세요")
        return v.strip()


@router.post("/members/{member_id}/password-reset-link")
async def reset_link(member_id: int, body: Reauth, response: Response, scope: StaffScope = Depends(admin_scope), db: AsyncSession = Depends(get_db)):
    """재설정 링크(24시간·1회) — 화면에 보이고 운영자가 다른 경로로 전한다. 대상이 운영자면 403"""
    response.headers["Cache-Control"] = NO_STORE
    result = await account.issue_reset_link(db, scope.viewer, member_id, body.password)
    await db.commit()
    return result


@router.post("/members/{member_id}/withdraw", status_code=204)
async def force_withdraw(member_id: int, body: ForcedWithdraw, scope: StaffScope = Depends(admin_scope), db: AsyncSession = Depends(get_db)):
    await account.force_withdraw(db, scope.viewer, member_id, body.password, body.reason)
    await db.commit()
    return Response(status_code=204, headers={"Cache-Control": NO_STORE})


class RevokeBody(Reauth):
    reason: str | None = Field(default=None, max_length=500)


@router.post("/members/{member_id}/revoke-sessions")
async def revoke_sessions(member_id: int, body: RevokeBody, scope: StaffScope = Depends(admin_scope), db: AsyncSession = Depends(get_db)):
    """강제 로그아웃 — 그 회원의 세션 모두 폐기(§4.13 재확인)"""
    n = await member_admin.revoke_member_sessions(db, scope.viewer, member_id, body.password, body.reason)
    await db.commit()
    return {"revoked": n}


# ── 그룹(명부) ──


@router.get("/member-groups")
async def list_groups(response: Response, scope: StaffScope = Depends(admin_scope), db: AsyncSession = Depends(get_db)):
    response.headers["Cache-Control"] = NO_STORE
    return {"items": await groups.list_groups(db)}


@router.get("/member-groups/{group_id}")
async def get_group(group_id: int, response: Response, scope: StaffScope = Depends(admin_scope), db: AsyncSession = Depends(get_db)):
    response.headers["Cache-Control"] = NO_STORE
    return await groups.group_detail(db, group_id)


@router.post("/member-groups", status_code=201)
async def create_group(body: groups.GroupBody, scope: StaffScope = Depends(admin_scope), db: AsyncSession = Depends(get_db)):
    result = await groups.create_group(db, scope.viewer, body)
    await db.commit()
    return result


@router.patch("/member-groups/{group_id}")
async def update_group(group_id: int, body: groups.GroupPatch, scope: StaffScope = Depends(admin_scope), db: AsyncSession = Depends(get_db)):
    result = await groups.update_group(db, scope.viewer, group_id, body)
    await db.commit()
    return result


@router.delete("/member-groups/{group_id}", status_code=204)
async def delete_group(group_id: int, scope: StaffScope = Depends(admin_scope), db: AsyncSession = Depends(get_db)):
    await groups.delete_group(db, scope.viewer, group_id)
    await db.commit()
    return Response(status_code=204)


@router.put("/member-groups/{group_id}/members")
async def set_group_members(group_id: int, body: groups.GroupMembers, scope: StaffScope = Depends(admin_scope), db: AsyncSession = Depends(get_db)):
    result = await groups.set_members(db, scope.viewer, group_id, body.member_ids)
    await db.commit()
    return result


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


