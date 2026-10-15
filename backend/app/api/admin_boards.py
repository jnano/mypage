"""게시판 관리 API — 설계도 §6 '게시판·카테고리·분류 그룹', §14.3 '권한 미리보기'. 운영자 전용."""

from types import SimpleNamespace
from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.logs import LogEntry, record
from app.admin.scope import StaffScope
from app.api.admin import staff_scope
from app.auth.viewer import Viewer, load_viewer
from app.boards import admin as service
from app.boards.schemas import (
    AccessList,
    BoardCreate,
    BoardUpdate,
    CategoryCreate,
    CategoryMerge,
    CategoryUpdate,
    GroupCreate,
    GroupUpdate,
    ModeratorList,
    Order,
)
from app.boards.templates import TEMPLATE_LABELS
from app.core.problems import Problem
from app.db.session import SessionLocal, get_db
from app.models import Board, BoardCategory, BoardGroup
from app.permissions import NO_ROLE, can, load_board_role

router = APIRouter()

Reason = Body(None, embed=True, max_length=500)


async def admin_scope(scope: StaffScope = Depends(staff_scope)) -> StaffScope:
    scope.require_admin()
    return scope


@router.get("/admin/boards")
async def list_boards(scope: StaffScope = Depends(admin_scope), db: AsyncSession = Depends(get_db)):
    groups = (await db.execute(select(BoardGroup).order_by(BoardGroup.sort_order, BoardGroup.id))).scalars()
    return {
        "boards": await service.list_boards(db),
        "groups": [{"id": g.id, "name": g.name, "sort_order": g.sort_order} for g in groups],
        "templates": [{"name": k, "label": v} for k, v in TEMPLATE_LABELS.items()],
    }


@router.post("/boards", status_code=201)
async def create_board(body: BoardCreate, scope: StaffScope = Depends(admin_scope)):
    async with SessionLocal() as db, db.begin():
        return await service.create_board(db, scope, body)


@router.get("/boards/{slug}")
async def get_board(slug: str, scope: StaffScope = Depends(admin_scope), db: AsyncSession = Depends(get_db)):
    board = await service.find_board(db, slug)
    return {
        "board": service.board_detail(board),
        "categories": await service.list_categories(db, board.id),
        **(await service.get_access(db, board.id)),
    }


@router.patch("/boards/{slug}")
async def update_board(slug: str, body: BoardUpdate, reason: str | None = Query(None, max_length=500), scope: StaffScope = Depends(admin_scope)):
    async with SessionLocal() as db, db.begin():
        return await service.update_board(db, scope, slug, body, reason)


@router.delete("/boards/{slug}")
async def delete_board(slug: str, scope: StaffScope = Depends(admin_scope)):
    async with SessionLocal() as db, db.begin():
        return await service.delete_board(db, scope, slug)


@router.post("/boards/{slug}/empty", status_code=202)
async def empty_board(slug: str, reason: str | None = Reason, scope: StaffScope = Depends(admin_scope)):
    async with SessionLocal() as db, db.begin():
        return await service.empty_board(db, scope, slug, reason)


# ── 명부·담당자 ──


@router.get("/boards/{slug}/access")
async def get_access(slug: str, scope: StaffScope = Depends(admin_scope), db: AsyncSession = Depends(get_db)):
    board = await service.find_board(db, slug)
    return await service.get_access(db, board.id)


@router.put("/boards/{slug}/access")
async def put_access(slug: str, body: AccessList, scope: StaffScope = Depends(admin_scope)):
    async with SessionLocal() as db, db.begin():
        board = await service.find_board(db, slug, lock=True)
        await service.put_access(db, scope, board, body)
        return await service.get_access(db, board.id) | {"invalidate": service._invalidate(slug)}


@router.get("/boards/{slug}/moderators")
async def get_moderators(slug: str, scope: StaffScope = Depends(admin_scope), db: AsyncSession = Depends(get_db)):
    board = await service.find_board(db, slug)
    return {"moderators": (await service.get_access(db, board.id))["moderators"]}


@router.put("/boards/{slug}/moderators")
async def put_moderators(slug: str, body: ModeratorList, scope: StaffScope = Depends(admin_scope)):
    async with SessionLocal() as db, db.begin():
        board = await service.find_board(db, slug, lock=True)
        await service.put_moderators(db, scope, board, body)
        return {"moderators": (await service.get_access(db, board.id))["moderators"], "invalidate": service._invalidate(slug)}


# ── 권한 미리보기(§14.2) — can() 을 그대로 부른다 ──

PREVIEW_ACTIONS = (
    ("board.list", "목록 보기"),
    ("post.read", "글 읽기"),
    ("post.create", "글쓰기"),
    ("comment.create", "댓글 쓰기"),
    ("attachment.upload", "파일 올리기"),
    ("attachment.download", "첨부 내려받기"),
    ("post.report", "신고"),
    ("post.moderate", "글 관리(담당자)"),
)


@router.get("/admin/boards/{slug}/permission-preview")
async def permission_preview(
    slug: str,
    level: int | None = Query(None, ge=0, le=99),
    member_id: int | None = Query(None, gt=0),
    scope: StaffScope = Depends(admin_scope),
    db: AsyncSession = Depends(get_db),
):
    """레벨 또는 회원을 고르면 행동별 가능 여부. 글 단위 행동은 '다른 사람의 공개 글 하나'를 놓고 판정한다."""
    board = await service.find_board(db, slug)
    if member_id is not None:
        viewer = await load_viewer(member_id)
        if viewer.member_id is None:
            raise Problem(404, "member_not_found", "회원을 찾을 수 없습니다")
    elif level is not None:
        viewer = Viewer(member_id=None if level == 0 else -1, level=level)  # 가상의 회원(-1: 아무 글의 작성자도 아님)
    else:
        raise Problem(422, "validation_error", "level 이나 member_id 중 하나가 필요합니다")
    role = await load_board_role(db, viewer, board.id) if viewer.member_id and viewer.member_id > 0 else NO_ROLE
    sample: Any = SimpleNamespace(id=0, member_id=None, is_guest=False, status="published", is_secret=False, is_blinded=False, min_view_level=None)
    results = []
    for action, label in PREVIEW_ACTIONS:
        allowed = can(viewer, role, action, board) if action in ("board.list", "post.create", "attachment.upload") else can(viewer, role, action, board, sample)
        results.append({"action": action, "label": label, "allowed": allowed})
    return {
        "subject": {"member_id": viewer.member_id if member_id else None, "level": viewer.level, "is_admin": viewer.is_admin},
        "role": {"is_moderator": role.is_moderator, "listed_read": role.listed_read, "listed_write": role.listed_write, "sanctions": sorted(role.sanctions)},
        "site_sanctions": sorted(viewer.sanctions),
        "actions": results,
    }


# ── 카테고리 ──


@router.get("/boards/{slug}/categories")
async def list_categories(slug: str, scope: StaffScope = Depends(admin_scope), db: AsyncSession = Depends(get_db)):
    board = await service.find_board(db, slug)
    return {"categories": await service.list_categories(db, board.id)}


@router.post("/boards/{slug}/categories", status_code=201)
async def create_category(slug: str, body: CategoryCreate, scope: StaffScope = Depends(admin_scope)):
    async with SessionLocal() as db, db.begin():
        board = await service.find_board(db, slug, lock=True)
        category_id = await service.save_category(db, scope, board.id, {"name": body.name})
        return {"category": {"id": category_id}, "invalidate": service._invalidate(slug)}


@router.patch("/categories/{category_id}")
async def update_category(category_id: int, body: CategoryUpdate, scope: StaffScope = Depends(admin_scope)):
    values = body.model_dump(exclude_unset=True, exclude_none=True)
    if not values:
        raise Problem(422, "validation_error", "바꿀 칸이 없습니다")
    async with SessionLocal() as db, db.begin():
        category, board = await service._category(db, category_id)
        await service.save_category(db, scope, board.id, values, category.id)
        return {"category": {"id": category.id}, "invalidate": service._invalidate(board.slug)}


@router.post("/categories/{category_id}/merge")
async def merge_category(category_id: int, body: CategoryMerge, scope: StaffScope = Depends(admin_scope)):
    async with SessionLocal() as db, db.begin():
        slug = await service.merge_category(db, scope, category_id, body)
        return {"merged": True, "invalidate": service._invalidate(slug)}


@router.delete("/categories/{category_id}")
async def delete_category(category_id: int, scope: StaffScope = Depends(admin_scope)):
    """삭제는 병합으로만(§4.2) — 글이 없는 카테고리만 바로 지운다."""
    async with SessionLocal() as db, db.begin():
        category, board = await service._category(db, category_id)
        used = next((c["posts"] for c in await service.list_categories(db, board.id) if c["id"] == category.id), 0)
        if used:
            raise Problem(409, "category_in_use", "글이 있는 카테고리는 다른 카테고리로 병합해야 지울 수 있습니다")
        await db.execute(delete(BoardCategory).where(BoardCategory.id == category.id))
        await record(db, scope.viewer, [LogEntry("category.delete", "board", board.id, board_id=board.id, before={"category_id": category.id, "name": category.name})])
        return {"deleted": True, "invalidate": service._invalidate(board.slug)}


@router.put("/boards/{slug}/categories/order")
async def order_categories(slug: str, body: Order, scope: StaffScope = Depends(admin_scope)):
    async with SessionLocal() as db, db.begin():
        board = await service.find_board(db, slug, lock=True)
        await service.reorder(db, BoardCategory, body.ids, BoardCategory.board_id == board.id)
        return {"ordered": True, "invalidate": service._invalidate(slug)}


# ── 분류 그룹 ──


@router.get("/board-groups")
async def list_groups(scope: StaffScope = Depends(admin_scope), db: AsyncSession = Depends(get_db)):
    groups = (await db.execute(select(BoardGroup).order_by(BoardGroup.sort_order, BoardGroup.id))).scalars()
    return {"groups": [{"id": g.id, "name": g.name, "sort_order": g.sort_order} for g in groups]}


@router.post("/board-groups", status_code=201)
async def create_group(body: GroupCreate, scope: StaffScope = Depends(admin_scope)):
    async with SessionLocal() as db, db.begin():
        order = (await db.execute(select(func.coalesce(func.max(BoardGroup.sort_order), -1) + 1))).scalar_one()
        group_id = (await db.execute(insert(BoardGroup).values(name=body.name, sort_order=order).returning(BoardGroup.id))).scalar_one()
        await record(db, scope.viewer, [LogEntry("board_group.create", "setting", group_id, after={"name": body.name})])
        return {"group": {"id": group_id}}


async def _group(db: AsyncSession, group_id: int) -> BoardGroup:
    group = (await db.execute(select(BoardGroup).where(BoardGroup.id == group_id).with_for_update())).scalar_one_or_none()
    if group is None:
        raise Problem(404, "group_not_found", "분류 그룹을 찾을 수 없습니다")
    return group


@router.patch("/board-groups/{group_id}")
async def update_group(group_id: int, body: GroupUpdate, scope: StaffScope = Depends(admin_scope)):
    async with SessionLocal() as db, db.begin():
        group = await _group(db, group_id)
        await db.execute(update(BoardGroup).where(BoardGroup.id == group.id).values(name=body.name))
        await record(db, scope.viewer, [LogEntry("board_group.update", "setting", group.id, before={"name": group.name}, after={"name": body.name})])
        return {"group": {"id": group.id}}


@router.delete("/board-groups/{group_id}")
async def delete_group(group_id: int, scope: StaffScope = Depends(admin_scope)):
    """그룹을 지우면 그 게시판들은 분류 없음(FK SET NULL)."""
    async with SessionLocal() as db, db.begin():
        group = await _group(db, group_id)
        await db.execute(delete(BoardGroup).where(BoardGroup.id == group.id))
        await record(db, scope.viewer, [LogEntry("board_group.delete", "setting", group.id, before={"name": group.name})])
        return {"deleted": True}


@router.put("/board-groups/order")
async def order_groups(body: Order, scope: StaffScope = Depends(admin_scope)):
    async with SessionLocal() as db, db.begin():
        await service.reorder(db, BoardGroup, body.ids)
        return {"ordered": True}


@router.put("/admin/boards/order")
async def order_boards(body: Order, scope: StaffScope = Depends(admin_scope)):
    """메뉴 순서 — 게시판 전체 id 를 순서대로."""
    async with SessionLocal() as db, db.begin():
        await service.reorder(db, Board, body.ids)
        await record(db, scope.viewer, [LogEntry("board.order", "setting", 0, after={"ids": body.ids})])
        return {"ordered": True, "invalidate": {"now": ["boards:structure"], "max": []}}
