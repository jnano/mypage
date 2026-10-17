"""틀 관리 — 홈블록 설계도 §4.1·§4.6·§7·§11.

틀은 이름 + 영역 여섯 칸의 블록 트리를 통째로 저장한다(If-Match 필수, 틀 행 잠금). 기본 틀은 하나 — 부분 UNIQUE 가
최종 판정이고, 바꾸기는 옛·새 기본 틀을 id 순으로 잠근다(D-401 교착 방지).
"""

from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, func, insert, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.logs import LogEntry, record
from app.auth.viewer import Viewer
from app.blocks import dangling, tree
from app.blocks import types as t
from app.blocks.routes import ROUTE_CLASSES
from app.core.problems import Problem
from app.files import block_images
from app.models import Attachment, Block, Board, Layout, LayoutBinding, Page

LayoutName = t.trimmed(1, 50)


class LayoutCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: LayoutName


class LayoutSave(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: LayoutName
    regions: dict[str, list[tree.BlockIn]]  # 영역 이름 → 블록 목록. outlet 은 렌더러가 놓으므로 보내지 않는다(§3.1)


class BindingsSave(BaseModel):
    """화면 종류 → 틀 id(없으면 기본 틀). 통째로 바꾼다"""

    model_config = ConfigDict(extra="forbid")

    bindings: dict[str, int | None]


def _not_found() -> Problem:
    return Problem(404, "layout_not_found", "틀을 찾을 수 없습니다")


def _name_taken() -> Problem:
    return Problem(409, "layout_name_taken", "같은 이름의 틀이 있습니다")


async def layout_detail(db: AsyncSession, layout_id: int) -> dict[str, Any]:
    layout = await db.get(Layout, layout_id)
    if layout is None:
        raise _not_found()
    regions = tree.nest(await tree.owner_blocks(db, "layout", layout_id))
    return {
        "id": layout.id,
        "name": layout.name,
        "is_default": layout.is_default,
        "version": layout.version,
        "regions": {r: regions.get(r, []) for r in t.REGIONS},
    }


async def list_layouts(db: AsyncSession) -> dict[str, Any]:
    blocks = select(func.count()).where(Block.layout_id == Layout.id).scalar_subquery()
    boards = select(func.count()).where(Board.layout_id == Layout.id).scalar_subquery()
    pages = select(func.count()).where(Page.layout_id == Layout.id).scalar_subquery()
    rows = await db.execute(
        select(Layout.id, Layout.name, Layout.is_default, Layout.version, Layout.updated_at,
               blocks.label("blocks"), boards.label("boards"), pages.label("pages")).order_by(Layout.name)  # fmt: skip
    )
    bindings = {b.route_class: b.layout_id for b in (await db.execute(select(LayoutBinding))).scalars()}
    return {
        "layouts": [dict(r._mapping) for r in rows],
        "bindings": {c: bindings.get(c) for c in ROUTE_CLASSES},
    }


async def create_layout(db: AsyncSession, viewer: Viewer, body: LayoutCreate) -> dict[str, Any]:
    layout = Layout(name=body.name, updated_by=viewer.member_id)
    db.add(layout)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise _name_taken() from None
    await record(db, viewer, [LogEntry("layout.create", "layout", layout.id, after={"name": layout.name})])
    return await layout_detail(db, layout.id)


def region_groups(regions: dict[str, list[tree.BlockIn]]) -> list[tuple[str | None, list[tree.BlockIn]]]:
    unknown = [r for r in regions if r not in t.REGIONS]
    if unknown:
        raise tree.problem([{"field": f"regions.{r}", "message": "없는 영역입니다(header·nav·top·aside·bottom·footer)"} for r in unknown])
    return [(r, regions.get(r, [])) for r in t.REGIONS]


def _groups(body: LayoutSave) -> list[tuple[str | None, list[tree.BlockIn]]]:
    return region_groups(body.regions)


async def save_layout(db: AsyncSession, viewer: Viewer, layout_id: int, body: LayoutSave, expected_version: int) -> dict[str, Any]:
    try:  # ① 입력 검증(DB 없음)
        flat = tree.validate_tree("layout", _groups(body), "regions")
    except tree.TreeErrors as e:
        raise tree.problem(e.errors) from None
    layout = await db.get(Layout, layout_id, with_for_update=True)  # ② 주인 행 잠금
    if layout is None:
        raise _not_found()
    if layout.version != expected_version:  # ③ 버전 비교
        raise Problem(412, "version_conflict", "다른 사람이 먼저 고쳤습니다", headers={"ETag": f'"{layout.version}"'})
    if errors := await tree.page_conflicts(db, layout_id, layout.is_default, tree.names_in(flat)):
        raise tree.problem(errors)
    changed = await tree.save_tree(db, viewer.member_id, "layout", layout_id, flat)  # ④
    old_name = layout.name
    layout.name = body.name
    layout.version = layout.version + 1  # ⑤
    layout.updated_by = viewer.member_id
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise _name_taken() from None
    after: dict[str, Any] = {k: v for k, v in changed.items() if v}
    if old_name != layout.name:
        after["name"] = layout.name
    await record(db, viewer, [LogEntry("layout.update", "layout", layout_id, before={"name": old_name} if "name" in after else None, after=after or None)])
    await dangling.request_recount(db)
    return await layout_detail(db, layout_id)


async def delete_layout(db: AsyncSession, viewer: Viewer, layout_id: int) -> None:
    """블록은 함께, 화면 종류 대응도 함께(CASCADE), 이 틀을 쓰던 게시판·페이지는 기본 쪽 틀로(SET NULL) — §11"""
    layout = await db.get(Layout, layout_id, with_for_update=True)
    if layout is None:
        raise _not_found()
    if layout.is_default:
        raise Problem(409, "default_layout", "기본 틀은 지울 수 없습니다. 다른 틀을 기본으로 정한 뒤 지우세요")
    await record(db, viewer, [LogEntry("layout.delete", "layout", layout_id, before={"name": layout.name})])
    images = select(Attachment.id).join(Block, Block.id == Attachment.block_id).where(Block.layout_id == layout_id)  # post-clause: exempt — 첨부 칸(글 아님)
    await block_images.release(db, (await db.execute(images)).scalars())  # 블록과 함께 떨어질 그림 — 지우기 전에 비공개로
    await db.execute(delete(Layout).where(Layout.id == layout_id))
    await dangling.request_recount(db)


async def set_default(db: AsyncSession, viewer: Viewer, layout_id: int) -> list[dict[str, str]]:
    """바꾸고 나서 경고를 돌려준다 — 틀을 고르지 않은 페이지들이 새 기본 틀을 쓰게 되는데, 그 페이지와 새 틀에 같은 이름의
    탐색·랜드마크가 있으면 그 페이지는 axe landmark-unique 위반이 된다(§10). 막지 않는다 — 기본 틀 바꾸기는 사이트 전체의
    전환이라 페이지 하나 때문에 막으면 운영자가 할 수 있는 일이 없다. 운영자가 그 페이지의 이름을 고친다(코드 검토 v11 N-2)"""
    # 옛 기본 틀과 새 틀을 한 문장으로 id 순 잠금 — 읽고 잠그는 사이에 기본 틀이 바뀌는 틈이 없다(D-401, 코드 검토 v7 N-4)
    locked = list(
        await db.execute(select(Layout.id, Layout.is_default).where(or_(Layout.is_default, Layout.id == layout_id)).order_by(Layout.id).with_for_update())
    )
    current = next((row.id for row in locked if row.is_default), None)
    if layout_id not in {row.id for row in locked}:
        raise _not_found()
    try:
        await db.execute(update(Layout).where(Layout.is_default, Layout.id != layout_id).values(is_default=False))
        await db.execute(update(Layout).where(Layout.id == layout_id).values(is_default=True))
    except IntegrityError:  # 그사이 다른 요청이 다른 틀을 기본으로 — 부분 UNIQUE 가 최종 판정(G-17)
        await db.rollback()
        raise Problem(409, "default_conflict", "다른 사람이 먼저 기본 틀을 바꿨습니다. 다시 불러오세요") from None
    await record(db, viewer, [LogEntry("layout.default", "layout", layout_id, before={"default": current})])
    names = {name: name for name in await tree.nav_labels(db, layout_ids=[layout_id])}
    unbound = await tree.page_conflicts(db, layout_id, True, names)  # 고른 페이지는 틀 저장 때 이미 막혔다 — 남는 것은 틀을 안 고른 페이지
    return [{"message": e["message"].replace("이 틀을 쓰는 페이지", "이제 이 틀을 쓰는 페이지")} for e in unbound]


async def save_bindings(db: AsyncSession, viewer: Viewer, body: BindingsSave) -> dict[str, int | None]:
    unknown = [c for c in body.bindings if c not in ROUTE_CLASSES]
    if unknown:
        raise tree.problem([{"field": f"bindings.{c}", "message": "없는 화면 종류입니다(board·search·member·auth)"} for c in unknown])
    wanted = {c: i for c, i in body.bindings.items() if i is not None}
    if wanted:
        found = set((await db.execute(select(Layout.id).where(Layout.id.in_(set(wanted.values()))).with_for_update())).scalars())
        missing = [c for c, i in wanted.items() if i not in found]
        if missing:
            raise tree.problem([{"field": f"bindings.{c}", "message": "없는 틀입니다"} for c in missing], "dangling_ref")
    before = {b.route_class: b.layout_id for b in (await db.execute(select(LayoutBinding))).scalars()}
    await db.execute(delete(LayoutBinding))
    if wanted:
        await db.execute(insert(LayoutBinding).values([{"route_class": c, "layout_id": i} for c, i in wanted.items()]))
    await record(db, viewer, [LogEntry("layout.bindings", "layout", 0, before=before, after=wanted)])
    return {c: wanted.get(c) for c in ROUTE_CLASSES}
