"""개인 조각 — 화면당 하나(§3.6). 공개 캐시본(비회원 기준) 위에 이 사람에게만 다른 것을 얹는다(§3.3).

캐시하지 않는다(Cache-Control: no-store). 판정은 서버 can()·post_mask() 한 곳.
"""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.viewer import GUEST, Viewer, get_viewer
from app.core.problems import Problem
from app.db.session import get_db
from app.models import Notification
from app.permissions import NO_ROLE, can, load_board_role, post_mask
from app.posts import queries

router = APIRouter()

MAX_IDS = 100
UNREAD_CAP = 99  # 99+ 까지만 센다(§7)


def _parse_ids(raw: str) -> list[int]:
    try:
        ids = sorted({int(x) for x in raw.split(",") if x.strip()})
    except ValueError:
        raise Problem(422, "validation_error", "ids 는 쉼표로 나눈 숫자입니다") from None
    if len(ids) > MAX_IDS or any(i <= 0 for i in ids):
        raise Problem(422, "validation_error", f"ids 는 양수 {MAX_IDS}개까지입니다")
    return ids


async def _unread_count(db: AsyncSession, member_id: int) -> int:
    capped = (
        select(Notification.id)
        .where(Notification.recipient_id == member_id, Notification.read_at.is_(None))
        .limit(UNREAD_CAP + 1)
        .subquery()
    )
    return (await db.execute(select(func.count()).select_from(capped))).scalar_one()


@router.get("/me/page-state")
async def page_state(
    board: str,
    ids: str = Query("", description="화면에 보이는 글 id(쉼표로 나눔)"),
    viewer: Viewer = Depends(get_viewer),
    db: AsyncSession = Depends(get_db),
):
    post_ids = _parse_ids(ids)
    body: dict = {
        "viewer": None,
        "board_role": {"is_moderator": False},
        "unmasked": [],
        "editable": [],
        "unread_notifications": 0,
        "unread_capped": False,
    }
    if viewer.member_id is None:
        return JSONResponse(body, headers={"Cache-Control": "no-store"})

    found = await queries.find_board(db, board)
    if found is None:
        raise Problem(404, "board_not_found", "게시판을 찾을 수 없습니다")
    role = await load_board_role(db, viewer, found.id)
    rows = await queries.find_posts_for_state(db, viewer, found.id, post_ids) if post_ids else []
    unread = await _unread_count(db, viewer.member_id)

    body |= {
        "viewer": {"member_id": viewer.member_id, "level": viewer.level, "is_admin": viewer.is_admin},
        "board_role": {"is_moderator": role.is_moderator},
        # 비회원 기준 캐시본에서는 가려졌지만 이 사람에게는 풀어도 되는 제목
        "unmasked": [
            {"id": r.id, "title": r.title}
            for r in rows
            if post_mask(GUEST, NO_ROLE, r) and not post_mask(viewer, role, r)
        ],
        "editable": [r.id for r in rows if can(viewer, role, "post.update", found, r)],
        "unread_notifications": unread,
        "unread_capped": unread > UNREAD_CAP,
    }
    return JSONResponse(body, headers={"Cache-Control": "no-store"})
