"""메뉴 관리 — 홈블록 설계도 §4.5·§4.6·§7·§11.

메뉴는 항목 트리를 통째로 저장한다: 보낸 트리에 id 가 있으면 고치고, 없으면 새로 넣고, 빠진 기존 항목은 지운다.
If-Match(버전) 필수 — 없으면 428, 다르면 412 + 지금 ETag. 한 요청은 메뉴 행 하나만 잠근다(§4.6).
"""

from collections.abc import Sequence
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.logs import LogEntry, record
from app.auth.viewer import Viewer
from app.blocks import types as t
from app.blocks.limits import MAX_MENU_DEPTH, MAX_MENU_ITEMS
from app.core.problems import Problem
from app.models import Board, Menu, MenuItem, Page

MenuName = t.trimmed(1, 50)


class MenuItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Annotated[int, Field(ge=1)] | None = None  # 있으면 이 메뉴의 기존 항목
    label: t.trimmed(1, 50)
    link: t.LinkTarget | None = None  # None = 링크 없는 묶음 제목(펼치기 단추만)
    min_level: Annotated[int, Field(ge=0, le=99)] = 0  # 표시 조건 — 권한이 아니다(§6)
    is_active: bool = True
    children: list["MenuItemIn"] = []


class MenuCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: MenuName


class MenuSave(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: MenuName
    items: list[MenuItemIn]


def _flatten(items: Sequence[MenuItemIn], depth: int = 1, path: str = "items") -> list[tuple[MenuItemIn, int, str]]:
    out = []
    for i, item in enumerate(items):
        field = f"{path}[{i}]"
        if depth > MAX_MENU_DEPTH:
            raise Problem(422, "validation_error", "입력값이 올바르지 않습니다", errors=[{"field": field, "message": f"메뉴는 {MAX_MENU_DEPTH}단까지입니다"}])
        out.append((item, depth, field))
        out += _flatten(item.children, depth + 1, f"{field}.children")
    return out


def _link_columns(link: Any) -> dict[str, Any]:
    cols: dict[str, Any] = {"page_id": None, "board_id": None, "url": None, "new_window": False}
    match link:
        case t.PageLink():
            return cols | {"link_kind": "page", "page_id": link.page_id, "new_window": link.new_window}
        case t.BoardLink():
            return cols | {"link_kind": "board", "board_id": link.board_id, "new_window": link.new_window}
        case t.UrlLink():
            return cols | {"link_kind": "url", "url": link.url, "new_window": link.new_window}
    return cols | {"link_kind": "none"}


def _link_out(row: Any) -> dict[str, Any] | None:
    match row.link_kind:
        case "page":
            return {"kind": "page", "page_id": row.page_id, "new_window": row.new_window}
        case "board":
            return {"kind": "board", "board_id": row.board_id, "new_window": row.new_window}
        case "url":
            return {"kind": "url", "url": row.url, "new_window": row.new_window}
    return None


def build_tree(rows: Sequence[Any]) -> list[dict[str, Any]]:
    """평평한 항목 행(정렬: sort_order, id) → 관리용 트리"""
    by_parent: dict[int | None, list[Any]] = {}
    for r in sorted(rows, key=lambda r: (r.sort_order, r.id)):
        by_parent.setdefault(r.parent_id, []).append(r)

    def walk(parent: int | None) -> list[dict[str, Any]]:
        return [
            {
                "id": r.id,
                "label": r.label,
                "link": _link_out(r),
                "min_level": r.min_level,
                "is_active": r.is_active,
                "children": walk(r.id),
            }
            for r in by_parent.get(parent, [])
        ]

    return walk(None)


ITEM_COLUMNS = (
    MenuItem.id, MenuItem.parent_id, MenuItem.sort_order, MenuItem.label, MenuItem.link_kind, MenuItem.page_id,
    MenuItem.board_id, MenuItem.url, MenuItem.new_window, MenuItem.min_level, MenuItem.is_active,
)  # fmt: skip


async def _items(db: AsyncSession, menu_id: int) -> list[Any]:
    # 행(Row)으로 읽는다 — ORM 객체면 아래 UPDATE 뒤에 세션의 옛 값이 남는다
    return list(await db.execute(select(*ITEM_COLUMNS).where(MenuItem.menu_id == menu_id)))


async def menu_detail(db: AsyncSession, menu_id: int) -> dict[str, Any]:
    menu = await db.get(Menu, menu_id)
    if menu is None:
        raise Problem(404, "menu_not_found", "메뉴를 찾을 수 없습니다")
    return {"id": menu.id, "name": menu.name, "version": menu.version, "items": build_tree(await _items(db, menu_id))}


async def list_menus(db: AsyncSession) -> list[dict[str, Any]]:
    count = select(func.count()).where(MenuItem.menu_id == Menu.id).scalar_subquery()
    rows = await db.execute(select(Menu.id, Menu.name, Menu.version, Menu.updated_at, count.label("items")).order_by(Menu.name))
    return [{"id": r.id, "name": r.name, "version": r.version, "updated_at": r.updated_at, "items": r.items} for r in rows]


def _name_taken() -> Problem:
    return Problem(409, "menu_name_taken", "같은 이름의 메뉴가 있습니다")


async def create_menu(db: AsyncSession, viewer: Viewer, body: MenuCreate) -> dict[str, Any]:
    menu = Menu(name=body.name)
    db.add(menu)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise _name_taken() from None
    await record(db, viewer, [LogEntry("menu.create", "menu", menu.id, after={"name": menu.name})])
    return await menu_detail(db, menu.id)


async def _check_refs(db: AsyncSession, flat: Sequence[tuple[MenuItemIn, int, str]]) -> None:
    """가리키는 페이지·게시판이 지금 있는가(FK 가 마지막에 막지만, 어느 항목인지 알려 주려고 먼저 본다 — §4.4 읽는 쪽 1)"""
    page_ids = {i.link.page_id for i, _, _ in flat if isinstance(i.link, t.PageLink)}
    board_ids = {i.link.board_id for i, _, _ in flat if isinstance(i.link, t.BoardLink)}
    pages = set((await db.execute(select(Page.id).where(Page.id.in_(page_ids)))).scalars()) if page_ids else set()
    boards = set((await db.execute(select(Board.id).where(Board.id.in_(board_ids)))).scalars()) if board_ids else set()
    errors = [
        {"field": f"{field}.link", "message": "없는 페이지·게시판입니다"}
        for item, _, field in flat
        if (isinstance(item.link, t.PageLink) and item.link.page_id not in pages)
        or (isinstance(item.link, t.BoardLink) and item.link.board_id not in boards)
    ]
    if errors:
        raise Problem(422, "dangling_ref", "가리키는 대상이 없습니다", errors=errors)


SNAPSHOT_KEYS = ("parent_id", "sort_order", "label", "link_kind", "page_id", "board_id", "url", "new_window", "min_level", "is_active")


def _snapshot(get: Any) -> dict[str, Any]:
    return {k: get(k) for k in SNAPSHOT_KEYS}


async def save_menu(db: AsyncSession, viewer: Viewer, menu_id: int, body: MenuSave, expected_version: int) -> dict[str, Any]:
    flat = _flatten(body.items)  # ① 입력 검증(DB 없음)
    if len(flat) > MAX_MENU_ITEMS:
        raise Problem(422, "validation_error", "입력값이 올바르지 않습니다", errors=[{"field": "items", "message": f"메뉴 항목은 {MAX_MENU_ITEMS}개까지입니다"}])
    sent_ids = [i.id for i, _, _ in flat if i.id is not None]
    if len(set(sent_ids)) != len(sent_ids):
        raise Problem(422, "validation_error", "입력값이 올바르지 않습니다", errors=[{"field": "items", "message": "같은 항목이 두 번 있습니다"}])

    menu = await db.get(Menu, menu_id, with_for_update=True)  # ② 주인 행 잠금
    if menu is None:
        raise Problem(404, "menu_not_found", "메뉴를 찾을 수 없습니다")
    if menu.version != expected_version:  # ③ 버전 비교
        raise Problem(412, "version_conflict", "다른 사람이 먼저 고쳤습니다", headers={"ETag": f'"{menu.version}"'})

    existing = {r.id: r for r in await _items(db, menu_id)}
    foreign = [field for i, _, field in flat if i.id is not None and i.id not in existing]
    if foreign:  # 이 메뉴의 항목이 아닌 id(§4.6)
        raise Problem(422, "item_not_in_menu", "이 메뉴의 항목이 아닙니다", errors=[{"field": f"{f}.id", "message": "이 메뉴의 항목이 아닙니다"} for f in foreign])
    await _check_refs(db, flat)

    # ④ 차이 적용 — 위에서 아래로(부모의 새 id 가 먼저 생긴다), 빠진 항목은 맨 나중에 지운다(옮겨 간 자식이 딸려 지워지지 않게)
    before = {i: _snapshot(lambda k, r=r: getattr(r, k)) for i, r in existing.items()}
    after: dict[int, dict[str, Any]] = {}

    async def apply(items: Sequence[MenuItemIn], parent_id: int | None) -> None:
        for order, item in enumerate(items):
            values = {
                "menu_id": menu_id, "parent_id": parent_id, "sort_order": order, "label": item.label,
                "min_level": item.min_level, "is_active": item.is_active, **_link_columns(item.link),
            }  # fmt: skip
            if item.id is None:
                item_id = (await db.execute(insert(MenuItem).values(values).returning(MenuItem.id))).scalar_one()
            else:
                item_id = item.id
                await db.execute(update(MenuItem).where(MenuItem.id == item_id).values(values))
            after[item_id] = _snapshot(values.get)
            await apply(item.children, item_id)

    await apply(body.items, None)
    removed = sorted(set(existing) - set(after))
    if removed:
        await db.execute(delete(MenuItem).where(MenuItem.id.in_(removed)))

    old_name = menu.name
    menu.name = body.name
    menu.version = menu.version + 1  # ⑤
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise _name_taken() from None

    # ⑥ 운영 기록 — 바뀐 항목만(§4.8)
    changed = {
        "added": [i for i in after if i not in before],
        "removed": removed,
        "updated": [i for i in after if i in before and before[i] != after[i]],
    }
    log_after: dict[str, Any] = {k: v for k, v in changed.items() if v}
    if old_name != menu.name:
        log_after["name"] = menu.name
    await record(db, viewer, [LogEntry("menu.update", "menu", menu_id, before={"name": old_name} if "name" in log_after else None, after=log_after or None)])
    return {"id": menu.id, "name": menu.name, "version": menu.version, "items": build_tree(await _items(db, menu_id))}


async def delete_menu(db: AsyncSession, viewer: Viewer, menu_id: int) -> None:
    """항목은 함께 지워진다(CASCADE). 이 메뉴를 가리키는 블록은 남고 그릴 때 건너뛴다 — 끊긴 참조(§11)"""
    menu = await db.get(Menu, menu_id, with_for_update=True)
    if menu is None:
        raise Problem(404, "menu_not_found", "메뉴를 찾을 수 없습니다")
    await record(db, viewer, [LogEntry("menu.delete", "menu", menu_id, before={"name": menu.name})])
    await db.execute(delete(Menu).where(Menu.id == menu_id))


async def menus_using(db: AsyncSession, *, board_id: int | None = None, page_id: int | None = None) -> list[int]:
    """그 게시판·페이지를 가리키는 메뉴 항목 id — 삭제 API 의 409 in_menu(FK RESTRICT 가 마지막에 막는다, §4.5)"""
    col, value = (MenuItem.board_id, board_id) if board_id is not None else (MenuItem.page_id, page_id)
    return list((await db.execute(select(MenuItem.id).where(col == value).order_by(MenuItem.id))).scalars())
