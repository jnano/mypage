"""알림함·수신 설정·게시판 구독 — 설계도 §6, §7. 개인 데이터라 캐시하지 않는다."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.viewer import Viewer, get_viewer
from app.core.problems import Problem
from app.db.session import get_db
from app.models import BoardSubscription, Notification, NotificationPref
from app.notifications import queries
from app.notifications.types import TYPES
from app.permissions import can, load_board_role
from app.posts import queries as post_queries

router = APIRouter()
NO_STORE = {"Cache-Control": "no-store"}


def _member(viewer: Viewer) -> int:
    if viewer.member_id is None:
        raise Problem(401, "login_required", "로그인이 필요합니다")
    return viewer.member_id


@router.get("/me/notifications")
async def list_notifications(
    cursor: str | None = Query(None, max_length=80),
    viewer: Viewer = Depends(get_viewer),
    db: AsyncSession = Depends(get_db),
):
    _member(viewer)
    try:
        after = queries.Cursor.decode(cursor) if cursor else None
    except ValueError:
        raise Problem(422, "validation_error", "cursor 가 올바르지 않습니다") from None
    rows, readable, next_cursor = await queries.list_notifications(db, viewer, after)
    items = []
    for r in rows:
        fixed = TYPES[r.type].path if r.type in TYPES else None  # 글이 아닌 알림(가입 신청 등)은 정해진 화면으로
        gone = fixed is None and r.post_id is None
        hidden = fixed is None and not gone and r.post_id not in readable
        if fixed is not None:
            path = fixed
        elif gone or hidden:
            path = None
        else:
            path = f"/boards/{r.board_slug}/{r.post_id}" + (f"#c-{r.comment_id}" if r.comment_id else "")
        items.append(
            {
                "id": r.id,
                "type": r.type,
                "actor_name": r.actor_name,
                "actor_count": r.actor_count,
                # 지운 글은 '삭제된 글', 지금 열 수 없는 글은 제목을 가린다(§7)
                "title": None if (gone or hidden) else r.title_snapshot,
                "masked": "deleted" if gone else "hidden" if hidden else None,
                "path": path,
                "read": r.read_at is not None,
                "created_at": r.created_at.isoformat(),
                "updated_at": r.updated_at.isoformat(),
            }
        )
    body = {"items": items, "next_cursor": next_cursor.encode() if next_cursor else None}
    return JSONResponse(body, headers=NO_STORE)


class ReadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: Annotated[list[Annotated[int, Field(gt=0)]], Field(max_length=200)] = []
    all: bool = False

    @model_validator(mode="after")
    def _one(self) -> "ReadRequest":
        if not self.ids and not self.all:
            raise ValueError("ids 또는 all 이 필요합니다")
        return self


@router.post("/me/notifications/read")
async def mark_read(body: ReadRequest, viewer: Viewer = Depends(get_viewer), db: AsyncSession = Depends(get_db)):
    member_id = _member(viewer)
    stmt = update(Notification).where(Notification.recipient_id == member_id, Notification.read_at.is_(None))
    if not body.all:
        stmt = stmt.where(Notification.id.in_(body.ids))
    result = await db.execute(stmt.values(read_at=func.now()))
    await db.commit()
    return {"read": result.rowcount or 0}


@router.get("/me/notification-prefs")
async def get_prefs(viewer: Viewer = Depends(get_viewer), db: AsyncSession = Depends(get_db)):
    member_id = _member(viewer)
    saved = dict(
        (await db.execute(select(NotificationPref.type, NotificationPref.enabled).where(NotificationPref.member_id == member_id))).all()
    )
    items = [{"type": t.name, "label": t.label, "enabled": saved.get(t.name, t.default_enabled)} for t in TYPES.values()]
    return JSONResponse({"items": items}, headers=NO_STORE)


@router.put("/me/notification-prefs")
async def put_prefs(body: dict[str, bool], viewer: Viewer = Depends(get_viewer), db: AsyncSession = Depends(get_db)):
    member_id = _member(viewer)
    unknown = sorted(set(body) - set(TYPES))
    if unknown:
        raise Problem(422, "validation_error", "알 수 없는 알림 종류입니다", errors=[{"field": k, "message": "unknown"} for k in unknown])
    if body:
        stmt = insert(NotificationPref).values([{"member_id": member_id, "type": k, "enabled": v} for k, v in body.items()])
        await db.execute(stmt.on_conflict_do_update(index_elements=["member_id", "type"], set_={"enabled": stmt.excluded.enabled}))
        await db.commit()
    return await get_prefs(viewer, db)


async def _subscribable_board(db: AsyncSession, viewer: Viewer, slug: str):
    _member(viewer)
    board = await post_queries.find_board(db, slug)
    if board is None:
        raise Problem(404, "board_not_found", "게시판을 찾을 수 없습니다")
    role = await load_board_role(db, viewer, board.id)
    if not can(viewer, role, "board.list", board):
        raise Problem(403, "board_forbidden", "이 게시판을 볼 권한이 없습니다")
    return board


@router.put("/boards/{slug}/subscription")
async def subscribe(slug: str, viewer: Viewer = Depends(get_viewer), db: AsyncSession = Depends(get_db)):
    board = await _subscribable_board(db, viewer, slug)
    await db.execute(
        insert(BoardSubscription).values(board_id=board.id, member_id=viewer.member_id).on_conflict_do_nothing()
    )
    await db.commit()
    return {"subscribed": True}


@router.delete("/boards/{slug}/subscription")
async def unsubscribe(slug: str, viewer: Viewer = Depends(get_viewer), db: AsyncSession = Depends(get_db)):
    member_id = _member(viewer)
    board = await post_queries.find_board(db, slug)
    if board is None:
        raise Problem(404, "board_not_found", "게시판을 찾을 수 없습니다")
    await db.execute(delete(BoardSubscription).where(BoardSubscription.board_id == board.id, BoardSubscription.member_id == member_id))
    await db.commit()
    return {"subscribed": False}

