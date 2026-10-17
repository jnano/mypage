"""기본 틀 만들기 — 홈블록 설계도 §3.6. 빈 DB(틀이 없어 코드의 대체 틀로 그려지는 사이트)에서 대체 틀과 같은 구성을
실제 행으로 만든다: 메뉴 '주 메뉴'(처음 · 메뉴 노출 게시판 · 검색 · 알림) + 기본 틀(머리: 사이트 이름·주 메뉴·검색·계정 /
본문 / 바닥: 저작권 문구). 한 트랜잭션 — 관리 화면 단추(POST /api/admin/layouts/bootstrap)와 개발 시드가 같은 함수를 쓴다.

마이그레이션은 이것을 부르지 않는다(운영 DB 에 자리 값을 넣지 않는다 — G-02). 이미 기본 틀이 있으면 409.
"""

from typing import Any

from sqlalchemy import func, select, true
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin import settings as site_settings
from app.admin.logs import LogEntry, record
from app.auth.viewer import Viewer
from app.blocks import tree
from app.core.problems import Problem
from app.models import Board, BoardGroup, Layout, Menu, MenuItem
from app.permissions import guest_listable_boards_clause

MENU_NAME = "주 메뉴"
LAYOUT_NAME = "기본 틀"
NAV_LABEL = "사이트"  # 대체 틀의 nav 이름과 같게 — 블록 기능을 켜기 전과 화면 읽기 프로그램이 읽는 말이 같다


def _exists() -> Problem:
    return Problem(409, "default_exists", "기본 틀이 이미 있습니다")


async def _free_name(db: AsyncSession, model: Any, base: str) -> str:
    """이름 UNIQUE — 같은 이름이 있으면 '이름 (2)' 꼴로(운영자가 먼저 만든 메뉴·틀을 덮지 않는다)"""
    taken = set((await db.execute(select(model.name).where(model.name.like(f"{base}%")))).scalars())
    if base not in taken:
        return base
    n = 2
    while f"{base} ({n})" in taken:
        n += 1
    return f"{base} ({n})"


async def menu_board_rows(db: AsyncSession) -> list[Any]:
    """대체 틀의 게시판 메뉴와 같은 게시판·순서(seo.queries.menu_boards — 메뉴 노출·비회원 목록 가능, 분류 그룹·순서대로)"""
    return list(
        await db.execute(
            select(Board.id, Board.name)
            .outerjoin(BoardGroup, BoardGroup.id == Board.group_id)
            .where(guest_listable_boards_clause(), Board.show_in_menu.is_(true()))
            .order_by(BoardGroup.sort_order.asc().nulls_first(), Board.sort_order, Board.id)
        )
    )


async def bootstrap(db: AsyncSession, viewer: Viewer) -> dict[str, Any]:
    if (await db.execute(select(func.count()).select_from(Layout).where(Layout.is_default))).scalar_one():
        raise _exists()
    menu = Menu(name=await _free_name(db, Menu, MENU_NAME))
    db.add(menu)
    await db.flush()
    items: list[dict[str, Any]] = [{"label": "처음", "link_kind": "url", "url": "/"}]
    items += [{"label": b.name, "link_kind": "board", "board_id": b.id} for b in await menu_board_rows(db)]
    items += [{"label": "검색", "link_kind": "url", "url": "/search"}, {"label": "알림", "link_kind": "url", "url": "/me/notifications"}]
    db.add_all(MenuItem(menu_id=menu.id, sort_order=i, **item) for i, item in enumerate(items))

    seo = await site_settings.load(db, "seo")
    assert isinstance(seo, site_settings.SeoSettings)
    layout = Layout(name=await _free_name(db, Layout, LAYOUT_NAME), is_default=True, updated_by=viewer.member_id)
    db.add(layout)
    try:
        await db.flush()
    except IntegrityError:  # 그사이 다른 요청이 기본 틀을 만들었다 — 부분 UNIQUE(is_default)가 최종 판정(G-17)
        await db.rollback()
        raise _exists() from None
    header = [
        tree.BlockIn(type="site_brand", config={"show_name": True}),
        tree.BlockIn(type="menu", config={"menu_id": menu.id, "label": NAV_LABEL, "depth": 1}),
        tree.BlockIn(type="search_box", config={}),
        tree.BlockIn(type="account", config={}),
    ]
    footer = [tree.BlockIn(type="footer_info", config={"copyright": f"© {seo.site_name}"})]
    flat = tree.validate_tree("layout", [("header", header), ("footer", footer)], "regions")
    await tree.save_tree(db, viewer.member_id, "layout", layout.id, flat)
    await record(
        db,
        viewer,
        [
            LogEntry("menu.create", "menu", menu.id, after={"name": menu.name, "items": len(items)}),
            LogEntry("layout.bootstrap", "layout", layout.id, after={"name": layout.name, "menu_id": menu.id}),
        ],
    )
    return {"layout_id": layout.id, "menu_id": menu.id}
