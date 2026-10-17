"""개인 조각 — 화면당 하나(§3.6). 공개 캐시본(비회원 기준) 위에 이 사람에게만 다른 것을 얹는다(§3.3).

캐시하지 않는다(Cache-Control: no-store). 판정은 서버 can()·post_mask() 한 곳.
"""

from fastapi import APIRouter, Depends, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.viewer import GUEST, Viewer, get_viewer
from app.blocks import frame
from app.core import cursor as cursors
from app.core.problems import Problem
from app.db.session import get_db
from app.models import BoardSubscription, Notification, PostReaction, PostScrap
from app.permissions import NO_ROLE, can, load_board_role, post_mask
from app.me import lists
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


async def _counts(db: AsyncSession, member_id: int, board_id: int, ids: list[int]) -> tuple[int, bool, list[int], list[int]]:
    """안 읽은 알림 수(99+ 까지)·이 게시판 구독 여부·요청한 글 가운데 추천·스크랩한 글(§6.1) — 쿼리 한 번."""
    capped = (
        select(Notification.id)
        .where(Notification.recipient_id == member_id, Notification.read_at.is_(None))
        .limit(UNREAD_CAP + 1)
        .subquery()
    )
    unread = select(func.count()).select_from(capped).scalar_subquery()
    subscribed = exists().where(BoardSubscription.board_id == board_id, BoardSubscription.member_id == member_id)
    liked = (
        select(func.array_agg(PostReaction.post_id))
        .where(PostReaction.post_id.in_(ids), PostReaction.member_id == member_id, PostReaction.kind == "like")
        .scalar_subquery()
    )
    scrapped = select(func.array_agg(PostScrap.post_id)).where(PostScrap.post_id.in_(ids), PostScrap.member_id == member_id).scalar_subquery()
    row = (
        await db.execute(select(unread.label("unread"), subscribed.label("subscribed"), liked.label("liked"), scrapped.label("scrapped")))
    ).one()
    return row.unread, row.subscribed, sorted(row.liked or []), sorted(row.scrapped or [])


@router.get("/me/page-state")
async def page_state(
    board: str | None = None,
    ids: str = Query("", description="화면에 보이는 글 id(쉼표로 나눔)"),
    blocks: str = Query("", description="틀 묶음의 personal_block_ids(쉼표로 나눔, 최대 30) — 홈블록 §5.4"),
    viewer: Viewer = Depends(get_viewer),
    db: AsyncSession = Depends(get_db),
):
    """게시판 화면의 개인 조각(board) 또는 틀의 회원 블록(blocks) — 틀과 화면은 Next 에서 따로 그려지므로 보통 따로
    부른다(홈블록 §5.2 '회원 블록 호출', 사용자 결정 A). blocks 만이면 게시판 몫은 비운다"""
    if board is not None and blocks:
        raise Problem(422, "validation_error", "board 와 blocks 는 따로 부릅니다(홈블록 §5.2 '회원 블록 호출')")
    if board is None:
        block_ids = _parse_ids(blocks)
        if len(block_ids) > frame.MAX_PERSONAL_BLOCKS:
            raise Problem(422, "validation_error", f"blocks 는 {frame.MAX_PERSONAL_BLOCKS}개까지입니다")
        found = {} if viewer.member_id is None else await frame.personal_blocks(db, viewer, block_ids)
        # viewer=false(만료·폐기된 쿠키) 면 화면은 비회원처럼 그린다 — '못 보는 블록'과 구분한다
        body = {"viewer": viewer.member_id is not None, "blocks": {str(k): v for k, v in found.items()}}
        return JSONResponse(jsonable_encoder(body), headers={"Cache-Control": "no-store"})
    post_ids = _parse_ids(ids)
    body: dict = {
        "viewer": None,
        "board_role": {"is_moderator": False},
        "unmasked": [],
        "editable": [],
        "liked": [],
        "scrapped": [],
        "unread_notifications": 0,
        "unread_capped": False,
        "subscribed": False,
    }
    if viewer.member_id is None:
        return JSONResponse(body, headers={"Cache-Control": "no-store"})

    found = await queries.find_board(db, board)
    if found is None:
        raise Problem(404, "board_not_found", "게시판을 찾을 수 없습니다")
    role = await load_board_role(db, viewer, found.id)
    rows = await queries.find_posts_for_state(db, viewer, found.id, post_ids) if post_ids else []
    unread, subscribed, liked, scrapped = await _counts(db, viewer.member_id, found.id, post_ids)

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
        "liked": liked,
        "scrapped": scrapped,
        "unread_notifications": unread,
        "unread_capped": unread > UNREAD_CAP,
        "subscribed": subscribed,
    }
    return JSONResponse(body, headers={"Cache-Control": "no-store"})


# ── 내 목록(§6.2) — 본인 것만, 최신순 키셋 커서 ──


def _member(viewer: Viewer) -> None:
    if viewer.member_id is None:
        raise Problem(401, "login_required", "로그인이 필요합니다")


def _iso(at) -> str | None:
    return at.isoformat() if at is not None else None


def _page(items: list[dict], next_cursor) -> JSONResponse:
    return JSONResponse({"items": items, "next_cursor": next_cursor.encode() if next_cursor else None}, headers={"Cache-Control": "no-store"})


@router.get("/me/posts")
async def my_posts(cursor: str | None = Query(None, max_length=80), viewer: Viewer = Depends(get_viewer), db: AsyncSession = Depends(get_db)):
    _member(viewer)
    rows, openable, next_cursor = await lists.my_posts(db, viewer, cursors.parse(cursor))
    items = [
        {
            "id": r.id,
            "title": r.title,
            "board": {"slug": r.board_slug, "name": r.board_name},
            "status": r.status,
            "is_secret": r.is_secret,
            "is_blinded": r.is_blinded,
            "created_at": r.created_at.isoformat(),
            "published_at": _iso(r.published_at),
            "stats": {"comments": r.comment_count or 0, "likes": r.like_count or 0},
            # 작성자도 게시판 조건을 통과해야 연다(§5.3) — 지금 열 수 없으면 제목·배지만, 링크 없음(검토 v4.0.9 N-1)
            "path": f"/boards/{r.board_slug}/{r.id}" if r.id in openable else None,
        }
        for r in rows
    ]
    return _page(items, next_cursor)


@router.get("/me/comments")
async def my_comments(cursor: str | None = Query(None, max_length=80), viewer: Viewer = Depends(get_viewer), db: AsyncSession = Depends(get_db)):
    _member(viewer)
    rows, readable, next_cursor = await lists.my_comments(db, viewer, cursors.parse(cursor))
    items = []
    for r in rows:
        open_ = r.post_id in readable
        items.append(
            {
                "id": r.id,
                "excerpt": r.excerpt,
                "is_blinded": r.is_blinded,
                "created_at": r.created_at.isoformat(),
                # 지금 읽을 수 없는 글은 제목·링크를 내지 않는다(알림함 §7 과 같다)
                "post": {"id": r.post_id, "title": r.post_title if open_ else None, "masked": None if open_ else "hidden"},
                "path": f"/boards/{r.board_slug}/{r.post_id}#c-{r.id}" if open_ else None,
            }
        )
    return _page(items, next_cursor)


@router.get("/me/scraps")
async def my_scraps(cursor: str | None = Query(None, max_length=80), viewer: Viewer = Depends(get_viewer), db: AsyncSession = Depends(get_db)):
    _member(viewer)
    rows, readable, next_cursor = await lists.my_scraps(db, viewer, cursors.parse(cursor))
    items = [
        {
            "post_id": r.post_id,
            "title": r.title if r.post_id in readable else None,
            "masked": None if r.post_id in readable else "hidden",
            "board": {"slug": r.board_slug, "name": r.board_name} if r.post_id in readable else None,
            "scrapped_at": r.created_at.isoformat(),
            "path": f"/boards/{r.board_slug}/{r.post_id}" if r.post_id in readable else None,
        }
        for r in rows
    ]
    return _page(items, next_cursor)
