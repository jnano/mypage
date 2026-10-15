"""신고 접수 — 설계도 §6 'POST /api/reports'. 처리·대기열은 admin_moderation."""

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse

from app.auth.viewer import Viewer, get_viewer
from app.reports import service
from app.reports.schemas import ReportCreate

router = APIRouter()


@router.post("/reports", status_code=201)
async def create_report(
    body: ReportCreate,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key", max_length=80),
    viewer: Viewer = Depends(get_viewer),
):
    status, result = await service.create_report(viewer, body, idempotency_key)
    return JSONResponse(result, status_code=status)
