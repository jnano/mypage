"""마크다운 미리보기 — 저장과 같은 서버 변환(§8.4). 변환기는 서버 한 곳뿐이다."""

from fastapi import APIRouter, Depends

from app.auth.viewer import Viewer, get_viewer
from app.core import rate_limit
from app.core.problems import Problem
from app.editor.content import build_content
from app.posts.schemas import PreviewRequest

router = APIRouter()


@router.post("/editor/preview")
async def preview(body: PreviewRequest, viewer: Viewer = Depends(get_viewer)) -> dict[str, str]:
    if viewer.member_id is None:
        raise Problem(401, "login_required", "로그인이 필요합니다")
    await rate_limit.hit("editor.preview", f"m:{viewer.member_id}")
    content = await build_content("markdown", body.markdown)
    return {"html": content.rendered}
