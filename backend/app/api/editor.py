"""마크다운 미리보기 — 저장과 같은 서버 변환(§8.4). 변환기는 서버 한 곳뿐이다."""

from fastapi import APIRouter, Depends, Request

from app.auth.viewer import Viewer, get_viewer
from app.core import rate_limit
from app.core.client_ip import client_ip
from app.editor.content import build_content
from app.posts.schemas import PreviewRequest

router = APIRouter()


@router.post("/editor/preview")
async def preview(body: PreviewRequest, request: Request, viewer: Viewer = Depends(get_viewer)) -> dict[str, str]:
    """회원은 회원 id, 비회원(비회원 글쓰기 화면 — 설계도 §6.3)은 실제 IP 로 센다. 쓰기 경계(내부 비밀)는 그대로"""
    subject = f"m:{viewer.member_id}" if viewer.member_id is not None else f"ip:{client_ip(request)}"
    await rate_limit.hit("editor.preview", subject)
    content = await build_content("markdown", body.markdown)
    return {"html": content.rendered}
