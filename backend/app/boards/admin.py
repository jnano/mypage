"""게시판 관리 — 설계도 §14.2 '게시판'. 운영자 전용(board.manage). 조치마다 운영 기록(§14.5).

쓰기는 짧은 트랜잭션 하나. 캐시 무효화는 무효화 표의 board.updated(§3.4).
게시판의 공개 조건(is_active·list_level·read_level)이 바뀌면 그 게시판 글의 첨부 공개 여부를 다시 맞춘다(§12):
같은 트랜잭션에서 공개 파일을 비공개로 내리고, 작업자가 글마다 reconcile 한다(board.reconcile).
"""

from typing import Any

from sqlalchemy import delete, func, insert, literal_column, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.logs import LogEntry, changed, record
from app.admin.scope import StaffScope
from app.blocks.menus import menus_using
from app.boards.schemas import AccessList, BoardCreate, BoardUpdate, CategoryMerge, ModeratorList
from app.boards.templates import template_values
from app.core import outbox
from app.core.invalidation import Invalidation, tags_for
from app.core.problems import Problem
from app.models import (
    Attachment,
    Board,
    BoardAccess,
    BoardCategory,
    BoardGroup,
    BoardModerator,
    BoardSlugHistory,
    Member,
    Post,
    PostCategory,
    Report,
)

# 복사·응답에 쓰는 설정 칸(식별·시각 칸 제외)
SETTING_COLUMNS = tuple(
    c.name for c in Board.__table__.columns if c.name not in {"id", "slug", "name", "is_system", "created_at", "updated_at"}
)
VISIBILITY_COLUMNS = frozenset({"is_active", "list_level", "read_level", "download_level"})


def board_detail(board: Board) -> dict[str, Any]:
    return {"id": board.id, "slug": board.slug, "name": board.name, "is_system": board.is_system} | {
        c: getattr(board, c) for c in SETTING_COLUMNS
    }


def _invalidate(*slugs: str) -> dict[str, list[str]]:
    now: list[str] = []
    later: list[str] = []
    for s in dict.fromkeys(slugs):
        inv = tags_for("board.updated", board_slug=s)
        now += [t for t in inv.now if t not in now]
        later += [t for t in inv.max if t not in later]
    return Invalidation(tuple(now), tuple(later)).as_dict()


async def find_board(db: AsyncSession, slug: str, *, lock: bool = False) -> Board:
    stmt = select(Board).where(Board.slug == slug)
    if lock:
        stmt = stmt.with_for_update()
    board = (await db.execute(stmt)).scalar_one_or_none()
    if board is None:
        raise Problem(404, "board_not_found", "게시판을 찾을 수 없습니다")
    return board


async def _slug_free(db: AsyncSession, slug: str, board_id: int | None = None) -> None:
    taken = (await db.execute(select(Board.id).where(Board.slug == slug))).scalar_one_or_none()
    if taken is not None and taken != board_id:
        raise Problem(409, "slug_taken", "이미 쓰는 주소입니다", errors=[{"field": "slug", "message": "이미 쓰는 주소입니다"}])


async def list_boards(db: AsyncSession) -> list[dict[str, Any]]:
    """관리 목록 — 분류 그룹별·글 수·최근 글 시각·신고 대기·승인 대기(§14.2). 쿼리 한 번."""
    published = Post.status == literal_column("'published'")
    stats = (
        select(  # post-clause: exempt — 관리 집계(행을 내주지 않음)
            Post.board_id,
            func.count().filter(published).label("posts"),
            func.max(Post.published_at).filter(published).label("last_post_at"),
            func.count().filter(Post.status == literal_column("'pending'")).label("pending"),
        )
        .group_by(Post.board_id)
        .subquery()
    )
    reports = (
        select(Report.board_id, func.count().label("reports"))
        .where(Report.status == literal_column("'open'"))
        .group_by(Report.board_id)
        .subquery()
    )
    rows = (
        await db.execute(
            select(
                Board.id, Board.slug, Board.name, Board.kind, Board.is_active, Board.is_system, Board.show_in_menu,
                Board.sort_order, Board.editor, BoardGroup.id.label("group_id"), BoardGroup.name.label("group_name"),
                func.coalesce(stats.c.posts, 0).label("posts"), stats.c.last_post_at,
                func.coalesce(stats.c.pending, 0).label("pending"), func.coalesce(reports.c.reports, 0).label("reports"),
            )  # fmt: skip
            .outerjoin(BoardGroup, BoardGroup.id == Board.group_id)
            .outerjoin(stats, stats.c.board_id == Board.id)
            .outerjoin(reports, reports.c.board_id == Board.id)
            .order_by(BoardGroup.sort_order.nulls_last(), BoardGroup.id, Board.sort_order, Board.id)
        )
    ).all()
    return [
        {
            "id": r.id, "slug": r.slug, "name": r.name, "kind": r.kind, "editor": r.editor,
            "is_active": r.is_active, "is_system": r.is_system, "show_in_menu": r.show_in_menu, "sort_order": r.sort_order,
            "group": {"id": r.group_id, "name": r.group_name} if r.group_id else None,
            "posts": r.posts, "last_post_at": r.last_post_at.isoformat() if r.last_post_at else None,
            "pending": r.pending, "reports": r.reports,
        }  # fmt: skip
        for r in rows
    ]


async def create_board(db: AsyncSession, scope: StaffScope, body: BoardCreate) -> dict[str, Any]:
    scope.require_admin()
    await _slug_free(db, body.slug)
    values = template_values(body.template)
    categories: list[str] = []
    if body.copy_from is not None:
        source = await find_board(db, body.copy_from)
        values = {c: getattr(source, c) for c in SETTING_COLUMNS}
        categories = list(
            (
                await db.execute(
                    select(BoardCategory.name).where(BoardCategory.board_id == source.id).order_by(BoardCategory.sort_order, BoardCategory.id)
                )
            ).scalars()
        )
    next_order = (await db.execute(select(func.coalesce(func.max(Board.sort_order), 0) + 1))).scalar_one()
    values = {"sort_order": next_order} | values | {"slug": body.slug, "name": body.name}
    board_id = (await db.execute(insert(Board).values(values).returning(Board.id))).scalar_one()
    if categories:
        await db.execute(insert(BoardCategory).values([{"board_id": board_id, "name": n, "sort_order": i} for i, n in enumerate(categories)]))
    # 옛 주소로 남은 같은 slug 는 새 게시판이 차지한다
    await db.execute(delete(BoardSlugHistory).where(BoardSlugHistory.old_slug == body.slug))
    await record(
        db,
        scope.viewer,
        [LogEntry("board.create", "board", board_id, board_id=board_id, after={"slug": body.slug, "template": body.template, "copy_from": body.copy_from})],
    )
    return {"board": {"id": board_id, "slug": body.slug}, "invalidate": _invalidate(body.slug)}


def _column_values(body: BoardUpdate) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for name in body.model_fields_set:
        value = getattr(body, name)
        if name == "spam_policy":
            values[name] = value.model_dump(exclude_unset=True) if value is not None else None
        elif name in ("display", "upload_policy"):
            values[name] = value.model_dump()
        else:
            values[name] = value
    return values


async def update_board(db: AsyncSession, scope: StaffScope, slug: str, body: BoardUpdate, reason: str | None) -> dict[str, Any]:
    scope.require_admin()
    board = await find_board(db, slug, lock=True)
    values = _column_values(body)
    new_slug = values.get("slug", board.slug)
    if new_slug != board.slug:
        if board.is_system:
            raise Problem(409, "system_board_slug", "시스템 게시판의 주소는 바꿀 수 없습니다")
        await _slug_free(db, new_slug, board.id)
    if values.get("group_id") is not None:
        exists = (await db.execute(select(BoardGroup.id).where(BoardGroup.id == values["group_id"]))).scalar_one_or_none()
        if exists is None:
            raise Problem(422, "validation_error", "입력값이 올바르지 않습니다", errors=[{"field": "group_id", "message": "없는 분류 그룹입니다"}])
    old_slug = board.slug  # 아래 ORM UPDATE 가 세션의 board 객체도 바꾼다
    current = {k: getattr(board, k) for k in values}
    before, after = changed(current, values)
    if not after:
        return {"board": board_detail(board), "invalidate": _invalidate(board.slug)}
    await db.execute(update(Board).where(Board.id == board.id).values(after | {"updated_at": func.now()}))
    if "slug" in after:
        await db.execute(delete(BoardSlugHistory).where(BoardSlugHistory.old_slug == new_slug))
        stmt = pg_insert(BoardSlugHistory).values(old_slug=old_slug, board_id=board.id)
        await db.execute(stmt.on_conflict_do_update(index_elements=["old_slug"], set_={"board_id": board.id, "changed_at": func.now()}))
    if VISIBILITY_COLUMNS & after.keys():
        await _demote_board_files(db, board.id)
    await record(db, scope.viewer, [LogEntry("board.update", "board", board.id, board_id=board.id, before=before, after=after, reason=reason)])
    await db.refresh(board)
    return {"board": board_detail(board), "invalidate": _invalidate(slug, new_slug)}


async def _demote_board_files(db: AsyncSession, board_id: int) -> None:
    """공개 조건이 바뀌면 그 게시판 첨부를 글마다 다시 맞춘다 — 공개 파일은 먼저 비공개로 표시해 둔다(§12, 좁히는 쪽이 안전)."""
    in_board = select(Post.id).where(Post.board_id == board_id)  # post-clause: exempt — 첨부 공개 여부 재계산 대상
    await db.execute(
        update(Attachment)
        .where(Attachment.post_id.in_(in_board), Attachment.visibility == literal_column("'public'"))
        .values(visibility="private")
    )
    await outbox.enqueue(db, [outbox.Event("board.reconcile", {"board_id": board_id, "after_post_id": 0})])


async def delete_board(db: AsyncSession, scope: StaffScope, slug: str) -> dict[str, Any]:
    """글이 0건일 때만(휴지통 포함). 시스템 게시판 금지(§14.2)."""
    scope.require_admin()
    board = await find_board(db, slug, lock=True)
    if board.is_system:
        raise Problem(409, "system_board", "시스템 게시판은 지울 수 없습니다")
    has_posts = (await db.execute(select(Post.id).where(Post.board_id == board.id).limit(1))).scalar_one_or_none()  # post-clause: exempt — 남은 글이 있는지만
    if has_posts is not None:
        raise Problem(409, "board_not_empty", "글이 남아 있어 지울 수 없습니다. 먼저 '게시판 비우기'를 하세요")
    # 메뉴 항목이 가리키면 먼저 메뉴에서 빼야 한다 — FK RESTRICT 가 마지막에 막지만 500 이 아니라 409 로(홈블록 §4.5·§11)
    if in_menu := await menus_using(db, board_id=board.id):
        raise Problem(
            409, "in_menu", "메뉴에 있는 게시판입니다. 먼저 메뉴에서 빼세요",
            errors=[{"field": f"menu_items.{i}", "message": "이 메뉴 항목이 가리킵니다"} for i in in_menu],
        )  # fmt: skip
    await record(db, scope.viewer, [LogEntry("board.delete", "board", board.id, before={"slug": board.slug, "name": board.name})])
    await db.execute(delete(Board).where(Board.id == board.id))
    return {"deleted": True, "invalidate": _invalidate(slug)}


async def empty_board(db: AsyncSession, scope: StaffScope, slug: str, reason: str | None) -> dict[str, Any]:
    """게시판 비우기 — 모든 글을 영구 삭제하는 작업을 건다(작업자가 나눠 지운다, board.empty)."""
    scope.require_admin()
    board = await find_board(db, slug, lock=True)
    count = (await db.execute(select(func.count()).select_from(Post).where(Post.board_id == board.id))).scalar_one()  # post-clause: exempt — 지울 글 수
    await outbox.enqueue(db, [outbox.Event("board.empty", {"board_id": board.id}, dedupe_key=f"board.empty:{board.id}:{count}")])
    await record(db, scope.viewer, [LogEntry("board.empty", "board", board.id, board_id=board.id, before={"posts": count}, reason=reason)])
    return {"queued": True, "posts": count}


# ── 카테고리 ──


async def list_categories(db: AsyncSession, board_id: int) -> list[dict[str, Any]]:
    used = select(PostCategory.category_id, func.count().label("n")).group_by(PostCategory.category_id).subquery()
    rows = (
        await db.execute(
            select(BoardCategory, func.coalesce(used.c.n, 0))
            .outerjoin(used, used.c.category_id == BoardCategory.id)
            .where(BoardCategory.board_id == board_id)
            .order_by(BoardCategory.sort_order, BoardCategory.id)
        )
    ).all()
    return [{"id": c.id, "name": c.name, "is_active": c.is_active, "sort_order": c.sort_order, "posts": n} for c, n in rows]


async def _category(db: AsyncSession, category_id: int) -> tuple[BoardCategory, Board]:
    row = (
        await db.execute(
            select(BoardCategory, Board).join(Board, Board.id == BoardCategory.board_id).where(BoardCategory.id == category_id).with_for_update(of=BoardCategory)
        )
    ).one_or_none()
    if row is None:
        raise Problem(404, "category_not_found", "카테고리를 찾을 수 없습니다")
    return row[0], row[1]


async def save_category(db: AsyncSession, scope: StaffScope, board_id: int, values: dict[str, Any], category_id: int | None = None) -> int:
    try:
        async with db.begin_nested():
            if category_id is None:
                order = (await db.execute(select(func.coalesce(func.max(BoardCategory.sort_order), -1) + 1).where(BoardCategory.board_id == board_id))).scalar_one()
                category_id = (await db.execute(insert(BoardCategory).values(board_id=board_id, sort_order=order, **values).returning(BoardCategory.id))).scalar_one()
                await record(db, scope.viewer, [LogEntry("category.create", "board", board_id, board_id=board_id, after={"category_id": category_id} | values)])
            else:
                await db.execute(update(BoardCategory).where(BoardCategory.id == category_id).values(values))
                await record(db, scope.viewer, [LogEntry("category.update", "board", board_id, board_id=board_id, after={"category_id": category_id} | values)])
    except IntegrityError:
        raise Problem(409, "category_name_taken", "같은 이름의 카테고리가 있습니다") from None
    return category_id


async def merge_category(db: AsyncSession, scope: StaffScope, category_id: int, body: CategoryMerge) -> str:
    """글을 into 로 옮기고(이미 둘 다 붙은 글은 한 줄로) 이 카테고리를 지운다. 같은 게시판끼리만."""
    source, board = await _category(db, category_id)
    target, _ = await _category(db, body.into)
    if target.board_id != source.board_id or target.id == source.id:
        raise Problem(422, "validation_error", "입력값이 올바르지 않습니다", errors=[{"field": "into", "message": "같은 게시판의 다른 카테고리여야 합니다"}])
    moved = select(PostCategory.post_id, literal_column(str(target.id))).where(PostCategory.category_id == source.id)
    await db.execute(
        pg_insert(PostCategory).from_select(["post_id", "category_id"], moved).on_conflict_do_nothing()
    )
    await db.execute(delete(PostCategory).where(PostCategory.category_id == source.id))  # FK RESTRICT — 옮긴 뒤 직접 지운다
    await db.execute(delete(BoardCategory).where(BoardCategory.id == source.id))
    await record(db, scope.viewer, [LogEntry("category.merge", "board", board.id, board_id=board.id, before={"category_id": source.id, "name": source.name}, after={"into": target.id})])
    return board.slug


async def reorder(db: AsyncSession, model, ids: list[int], *where) -> None:
    """ids 순서대로 sort_order 0..n. 범위(where) 밖 id 가 있거나 빠지면 422."""
    current = set((await db.execute(select(model.id).where(*where))).scalars())
    if set(ids) != current:
        raise Problem(422, "validation_error", "입력값이 올바르지 않습니다", errors=[{"field": "ids", "message": "목록 전체를 빠짐없이 보내야 합니다"}])
    for i, id_ in enumerate(ids):
        await db.execute(update(model).where(model.id == id_).values(sort_order=i))


# ── 명부·담당자 ──


async def get_access(db: AsyncSession, board_id: int) -> dict[str, Any]:
    access = (await db.execute(select(BoardAccess).where(BoardAccess.board_id == board_id).order_by(BoardAccess.subject_type, BoardAccess.subject_id))).scalars()
    mods = (
        await db.execute(
            select(Member.id, Member.display_name).join(BoardModerator, BoardModerator.member_id == Member.id).where(BoardModerator.board_id == board_id).order_by(Member.id)
        )
    ).all()
    return {
        "entries": [{"subject_type": a.subject_type, "subject_id": a.subject_id, "can_read": a.can_read, "can_write": a.can_write} for a in access],
        "moderators": [{"id": m.id, "name": m.display_name} for m in mods],
    }


async def put_access(db: AsyncSession, scope: StaffScope, board: Board, body: AccessList) -> None:
    scope.require_admin()
    before = await get_access(db, board.id)
    await db.execute(delete(BoardAccess).where(BoardAccess.board_id == board.id))
    if body.entries:
        await db.execute(insert(BoardAccess).values([{"board_id": board.id} | e.model_dump() for e in body.entries]))
    await record(
        db, scope.viewer,
        [LogEntry("board.access", "board", board.id, board_id=board.id, before={"entries": before["entries"]}, after={"entries": [e.model_dump() for e in body.entries]})],
    )  # fmt: skip


async def put_moderators(db: AsyncSession, scope: StaffScope, board: Board, body: ModeratorList) -> None:
    scope.require_admin()
    found = set((await db.execute(select(Member.id).where(Member.id.in_(body.member_ids), Member.status == literal_column("'active'")))).scalars())
    missing = [i for i in body.member_ids if i not in found]
    if missing:
        raise Problem(422, "validation_error", "입력값이 올바르지 않습니다", errors=[{"field": "member_ids", "message": f"없는 회원입니다: {missing}"}])
    before = [m["id"] for m in (await get_access(db, board.id))["moderators"]]
    await db.execute(delete(BoardModerator).where(BoardModerator.board_id == board.id))
    if body.member_ids:
        await db.execute(insert(BoardModerator).values([{"board_id": board.id, "member_id": m} for m in body.member_ids]))
    await record(db, scope.viewer, [LogEntry("board.moderators", "board", board.id, board_id=board.id, before={"member_ids": before}, after={"member_ids": body.member_ids})])
