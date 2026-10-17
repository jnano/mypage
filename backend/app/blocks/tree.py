"""블록 트리 검증·저장 — 홈블록 설계도 §4.3·§4.6·§4.7·§10. 틀(걸음 5)과 페이지 본문(걸음 6)이 함께 쓴다.

트리는 통째로 받는다: 보낸 블록에 id 가 있으면 고치고, 없으면 넣고, 빠진 기존 블록은 맨 나중에 지운다(옮긴 자식이
딸려 지워지지 않게). 블록 id 를 유지하는 이유는 그림 첨부가 block_id 로 블록을 가리키기 때문이다(§4.6).
검증 오류는 모아서 한 번에 낸다 — errors[].field 는 `regions.header[2].config.items[1].url` 꼴(§7).
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import and_, delete, insert, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin import settings as site_settings
from app.blocks import types as t
from app.blocks.limits import MAX_BLOCKS_PER_OWNER, MAX_DYNAMIC_BLOCKS, MAX_MODULES_PER_PAGE
from app.core.problems import Problem
from app.files import block_images
from app.models import Attachment, Block, Board, Menu, Page

Owner = Literal["layout", "page"]
STRUCTURE = ("group", "columns")
# 랜드마크 이름이 되는 칸 — 같은 틀(+ 페이지)에서 겹치면 axe landmark-unique(D-703) 위반이라 저장 때 막는다(§10)
NAMED_NAV = ("menu", "sub_menu", "breadcrumb")


class BlockIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Annotated[int, Field(ge=1)] | None = None  # 있으면 이 주인의 기존 블록
    type: str
    config: dict[str, Any] = {}
    audience: Literal["all", "guest", "member"] = "all"
    min_level: Annotated[int, Field(ge=0, le=99)] = 0
    is_active: bool = True
    column_index: Annotated[int, Field(ge=0, le=3)] | None = None  # columns 의 자식만
    children: list["BlockIn"] = []


@dataclass
class Refs:
    pages: set[int] = field(default_factory=set)
    boards: set[int] = field(default_factory=set)
    menus: set[int] = field(default_factory=set)
    attachments: set[int] = field(default_factory=set)


@dataclass
class FlatBlock:
    item: BlockIn
    field: str
    region: str | None
    parent: "FlatBlock | None"
    sort_order: int
    config: dict[str, Any]
    refs: Refs
    id: int | None = None  # 넣은 뒤에 채운다


class TreeErrors(Exception):
    def __init__(self, errors: list[dict[str, str]]):
        self.errors = errors


_MD_ATTACHMENT = re.compile(r"attachment:([1-9][0-9]{0,17})")


def collect_refs(model: Any, refs: Refs | None = None) -> Refs:
    """설정 안의 참조(JSONB — FK 없음, §4.4 읽는 쪽 셋)를 모은다"""
    refs = refs if refs is not None else Refs()
    match model:
        case t.PageLink():
            refs.pages.add(model.page_id)
        case t.BoardLink():
            refs.boards.add(model.board_id)
        case t.Text():
            refs.attachments |= {int(m) for m in _MD_ATTACHMENT.findall(model.source)}
        case t.Module() if model.module == "board":
            refs.boards.add(int(model.params["board_id"]))
    if isinstance(model, BaseModel):
        for name in type(model).model_fields:
            value = getattr(model, name)
            if name == "menu_id":
                refs.menus.add(value)
            elif name == "board_ids":
                refs.boards |= set(value)
            elif name in ("attachment_id", "logo_attachment_id") and value is not None:
                refs.attachments.add(value)
            elif isinstance(value, (BaseModel, list)):
                for v in value if isinstance(value, list) else [value]:
                    collect_refs(v, refs)
    return refs


def _loc(err: dict) -> str:
    out = ""
    for part in err["loc"]:
        out += f"[{part}]" if isinstance(part, int) else f".{part}"
    return out


def validate_tree(
    owner: Owner,
    groups: Sequence[tuple[str | None, Sequence[BlockIn]]],
    path: str,
    taken: dict[str, str] | None = None,
) -> list[FlatBlock]:
    """(영역, 블록 목록) 묶음들 → 평평한 목록. 오류는 모아서 TreeErrors. path 는 오류 칸 이름의 앞부분.
    taken = 같은 화면에 함께 그려질 다른 주인(페이지 ↔ 그 틀)의 탐색·랜드마크 이름 → 어디의 것인지(§10, 코드 검토 v7 N-3)"""
    errors: list[dict[str, str]] = []
    flat: list[FlatBlock] = []
    labels: dict[str, str] = dict(taken or {})

    def err(f: str, message: str) -> None:
        errors.append({"field": f, "message": message})

    def visit(item: BlockIn, f: str, region: str | None, parent: FlatBlock | None, order: int) -> None:
        spec = t.SPECS.get(item.type)
        if spec is None or item.type not in t.STORED_BLOCK_TYPES:
            err(f"{f}.type", "쓸 수 없는 블록 종류입니다")
            return
        if owner not in spec.places:
            err(f"{f}.type", "여기에 놓을 수 없는 블록입니다")
            return
        try:
            model = t.validate_config(item.type, item.config)
        except ValidationError as e:
            for x in e.errors():
                err(f"{f}.config{_loc(x)}", x["msg"])
            return
        if parent is None:
            if item.column_index is not None:
                err(f"{f}.column_index", "칸 번호는 칸 나누기 블록의 자식만 가집니다")
        elif parent.item.type == "columns":
            count = parent.config["count"]
            if item.column_index is None or item.column_index >= count:
                err(f"{f}.column_index", f"칸 번호는 0~{count - 1} 입니다")
        elif item.column_index is not None:
            err(f"{f}.column_index", "칸 번호는 칸 나누기 블록의 자식만 가집니다")
        if parent is not None and item.type in STRUCTURE:
            err(f"{f}.type", "묶음 안에 묶음·칸 나누기는 둘 수 없습니다(깊이 2)")
            return
        if item.children and item.type not in STRUCTURE:
            err(f"{f}.children", "자식 블록은 묶음·칸 나누기에만 둡니다")
            return
        name = None
        if item.type in NAMED_NAV:
            name = getattr(model, "label")
        elif isinstance(model, t.Group) and model.landmark:
            name = model.title
        if name is not None:
            if name in labels:
                err(f"{f}.config", f"같은 이름의 탐색·랜드마크가 이미 있습니다: {name}({labels[name]}) — 이름이 달라야 합니다")
            labels.setdefault(name, f)
        node = FlatBlock(item, f, region, parent, order, model.model_dump(mode="json"), collect_refs(model))
        flat.append(node)
        for i, child in enumerate(item.children):
            visit(child, f"{f}.children[{i}]", None, node, i)

    for region, items in groups:
        base = f"{path}.{region}" if region else path
        for i, item in enumerate(items):
            visit(item, f"{base}[{i}]", region, None, i)

    if len(flat) > MAX_BLOCKS_PER_OWNER:
        err(path, f"블록은 {MAX_BLOCKS_PER_OWNER}개까지입니다")
    if sum(b.item.type in t.DYNAMIC_BLOCK_TYPES for b in flat) > MAX_DYNAMIC_BLOCKS:
        err(path, f"데이터를 불러오는 블록(최근 글·댓글·게시판 바로가기·모듈)은 {MAX_DYNAMIC_BLOCKS}개까지입니다")
    if sum(b.item.type == "module" for b in flat) > MAX_MODULES_PER_PAGE:
        err(path, f"모듈 자리는 페이지마다 {MAX_MODULES_PER_PAGE}개입니다")
    ids = [b.item.id for b in flat if b.item.id is not None]
    if len(set(ids)) != len(ids):
        err(path, "같은 블록이 두 번 있습니다")
    seen: dict[int, str] = {}
    for b in flat:  # 그림은 블록 하나에만(block_id 하나) — DB 까지 가기 전에 어느 블록인지 알린다(코드 검토 v7 N-2)
        for a in sorted(b.refs.attachments):
            if a in seen:
                err(f"{b.field}.config", f"같은 그림이 이미 다른 블록({seen[a]})에 있습니다 — 그림은 블록 하나에만")
            seen.setdefault(a, b.field)
    if errors:
        raise TreeErrors(errors)
    return flat


def problem(errors: list[dict[str, str]], code: str = "validation_error") -> Problem:
    return Problem(422, code, "입력값이 올바르지 않습니다", errors=errors)


BLOCK_COLUMNS = (
    Block.id, Block.parent_id, Block.region, Block.column_index, Block.sort_order, Block.type, Block.config,
    Block.audience, Block.min_level, Block.is_active,
)  # fmt: skip


async def owner_blocks(db: AsyncSession, owner: Owner, owner_id: int) -> list[Any]:
    col = Block.layout_id if owner == "layout" else Block.page_id
    return list(await db.execute(select(*BLOCK_COLUMNS).where(col == owner_id)))  # post-clause: exempt — 블록 칸(글 아님)


def nest(rows: Iterable[Any]) -> dict[str | None, list[dict[str, Any]]]:
    """블록 행 → 영역마다(페이지는 None) 중첩된 관리용 트리"""
    by_parent: dict[int | None, list[Any]] = {}
    for r in sorted(rows, key=lambda r: (r.sort_order, r.id)):
        by_parent.setdefault(r.parent_id, []).append(r)

    def node(r: Any) -> dict[str, Any]:
        out = {"id": r.id, "type": r.type, "config": r.config, "audience": r.audience, "min_level": r.min_level, "is_active": r.is_active}
        if r.column_index is not None:
            out["column_index"] = r.column_index
        out["children"] = [node(c) for c in by_parent.get(r.id, [])]
        return out

    regions: dict[str | None, list[dict[str, Any]]] = {}
    for r in by_parent.get(None, []):
        regions.setdefault(r.region, []).append(node(r))
    return regions


async def _check_refs(db: AsyncSession, flat: Sequence[FlatBlock]) -> None:
    want = Refs()
    for b in flat:
        want.pages |= b.refs.pages
        want.boards |= b.refs.boards
        want.menus |= b.refs.menus
    have = Refs(
        pages=set((await db.execute(select(Page.id).where(Page.id.in_(want.pages)))).scalars()) if want.pages else set(),
        boards=set((await db.execute(select(Board.id).where(Board.id.in_(want.boards)))).scalars()) if want.boards else set(),
        menus=set((await db.execute(select(Menu.id).where(Menu.id.in_(want.menus)))).scalars()) if want.menus else set(),
    )
    errors = [
        {"field": f"{b.field}.config", "message": f"없는 {kind}입니다: {sorted(missing)}"}
        for b in flat
        for kind, missing in (
            ("페이지", b.refs.pages - have.pages),
            ("게시판", b.refs.boards - have.boards),
            ("메뉴", b.refs.menus - have.menus),
        )
        if missing
    ]
    if errors:
        raise problem(errors, "dangling_ref")


async def save_tree(db: AsyncSession, member_id: int | None, owner: Owner, owner_id: int, flat: Sequence[FlatBlock]) -> dict[str, list[int]]:
    """주인 행을 잠근 뒤에 부른다(§4.6). 바뀐 블록 id 를 돌려준다(운영 기록용)"""
    existing = {r.id: r for r in await owner_blocks(db, owner, owner_id)}
    policy = await site_settings.load(db, "site_upload")
    assert isinstance(policy, site_settings.SiteUploadPolicy)
    over = [b.field for b in flat if len(b.refs.attachments) > policy.max_files]
    if over:  # 블록 하나의 그림 수(사이트 업로드 한도, §4.7)
        raise problem([{"field": f"{f}.config", "message": f"블록 하나에 그림은 {policy.max_files}개까지입니다"} for f in over])
    # 이 저장 전에 이 주인의 블록에 붙어 있던 그림 — 블록 사이로 옮길 수 있다(지운 블록의 그림도 다른 블록이 받으면 옮겨진다)
    owned = set((await db.execute(select(Attachment.id).where(Attachment.block_id.in_(list(existing) or [0])))).scalars())  # post-clause: exempt — 첨부 칸(글 아님)
    foreign = [b.field for b in flat if b.item.id is not None and b.item.id not in existing]
    if foreign:
        raise problem([{"field": f"{f}.id", "message": "이 틀·페이지의 블록이 아닙니다"} for f in foreign], "block_not_in_owner")
    await _check_refs(db, flat)

    owner_col = "layout_id" if owner == "layout" else "page_id"
    changed: dict[str, list[int]] = {"added": [], "updated": [], "removed": []}
    for b in flat:  # 위에서 아래로 — 부모가 먼저라 자식이 부모의 새 id 를 안다
        values = {
            owner_col: owner_id, "region": b.region, "parent_id": b.parent.id if b.parent else None,
            "column_index": b.item.column_index, "sort_order": b.sort_order, "type": b.item.type, "config": b.config,
            "audience": b.item.audience, "min_level": b.item.min_level, "is_active": b.item.is_active,
        }  # fmt: skip
        if b.item.id is None:
            b.id = (await db.execute(insert(Block).values(values).returning(Block.id))).scalar_one()
            changed["added"].append(b.id)
        else:
            b.id = b.item.id
            old = existing[b.id]
            if any(getattr(old, k) != v for k, v in values.items() if k != owner_col):
                await db.execute(update(Block).where(Block.id == b.id).values(values))
                changed["updated"].append(b.id)
    removed = sorted(set(existing) - {b.id for b in flat})
    if removed:  # 그 블록의 그림은 FK SET NULL 로 임시가 되어 24시간 뒤 정리된다(§4.7)
        await db.execute(delete(Block).where(Block.id.in_(removed)))
        changed["removed"] = removed
    await _attach_images(db, member_id, flat, owned)
    kept = {a for b in flat for a in b.refs.attachments}
    await block_images.release(db, owned - kept)  # 떨어진 그림은 공개 저장소에 남지 않게
    await block_images.reconcile(db, [b.id for b in flat if b.refs.attachments and b.id is not None])
    return changed


async def _attach_images(db: AsyncSession, member_id: int | None, flat: Sequence[FlatBlock], owned: set[int]) -> None:
    """블록 그림 붙이기·떼기(§4.7). 최종 판정은 UPDATE 조건 — 이미 이 블록의 그림이거나, 이 저장 전에 같은 주인(틀·페이지)의
    블록에 붙어 있던 그림(블록 사이 옮기기 — 올린 사람이 누구든, 코드 검토 v7 N-1)이거나, 저장하는 사람의 임시 업로드인
    그림 파일. 영향 행 수가 모자라면 422(같은 임시 파일을 다른 글·블록이 먼저 붙였거나 남의 파일·그림 아님)"""
    for b in flat:  # 먼저 떼기 — 한 저장 안에서 그림이 다른 블록으로 옮겨 갈 수 있다
        keep = sorted(b.refs.attachments)
        stmt = update(Attachment).where(Attachment.block_id == b.id)
        if keep:
            stmt = stmt.where(Attachment.id.not_in(keep))
        await db.execute(stmt.values(block_id=None))
    errors = []
    for b in flat:
        want = sorted(b.refs.attachments)
        if not want:
            continue
        mine_temp = and_(Attachment.block_id.is_(None), or_(Attachment.uploader_id == member_id, Attachment.id.in_(owned or [0])))
        result = await db.execute(
            update(Attachment)
            .where(
                Attachment.id.in_(want),
                Attachment.post_id.is_(None),
                Attachment.is_image.is_(True),
                or_(Attachment.block_id == b.id, mine_temp),
            )
            .values(block_id=b.id)
        )
        if result.rowcount != len(want):
            errors.append({"field": f"{b.field}.config", "message": "붙일 수 없는 그림입니다(내가 올린 임시 그림이나 이 블록의 그림만)"})
    if errors:
        raise problem(errors, "attachment_unavailable")



def nav_name(block_type: str, config: dict[str, Any]) -> str | None:
    """탐색·랜드마크 이름(§10) — 메뉴 셋의 label, 랜드마크 묶음의 title. 저장된 설정(dict)에서"""
    if block_type in NAMED_NAV:
        return config.get("label") or ("현재 위치" if block_type == "breadcrumb" else None)
    if block_type == "group" and config.get("landmark"):
        return config.get("title")
    return None


async def nav_labels(db: AsyncSession, *, layout_ids: Iterable[int] = (), page_ids: Iterable[int] = ()) -> dict[str, str]:
    """주인들의 탐색·랜드마크 이름 → 어디의 것인지('틀 n'·'페이지 n'). 한 문장"""
    layouts, pages = sorted(set(layout_ids)), sorted(set(page_ids))
    if not layouts and not pages:
        return {}
    rows = await db.execute(
        select(Block.type, Block.config, Block.layout_id, Block.page_id).where(  # post-clause: exempt — 블록 칸(글 아님)
            or_(Block.layout_id.in_(layouts or [0]), Block.page_id.in_(pages or [0])),
            Block.type.in_([*NAMED_NAV, "group"]),
            Block.is_active.is_(True),
        )
    )
    out: dict[str, str] = {}
    for r in rows:
        if (name := nav_name(r.type, r.config)) is not None:
            out.setdefault(name, f"틀 {r.layout_id}" if r.layout_id else f"페이지 {r.page_id}")
    return out


def names_in(flat: Sequence[FlatBlock]) -> dict[str, str]:
    """검증한 트리의 탐색·랜드마크 이름 → 칸 경로"""
    out: dict[str, str] = {}
    for b in flat:
        if (name := nav_name(b.item.type, b.config)) is not None:
            out.setdefault(name, b.field)
    return out


async def page_conflicts(db: AsyncSession, layout_id: int, is_default: bool, names: dict[str, str]) -> list[dict[str, str]]:
    """틀을 저장할 때 — 그 틀을 쓰는 페이지(고른 페이지, 기본 틀이면 틀을 안 고른 페이지)의 이름과 겹치는 것(§10). 한 문장"""
    if not names:
        return []
    uses = Page.layout_id == layout_id
    if is_default:
        uses = or_(uses, Page.layout_id.is_(None))
    rows = await db.execute(
        select(Block.type, Block.config, Page.path)  # post-clause: exempt — 블록 칸(글 아님)
        .join(Page, Page.id == Block.page_id)
        .where(uses, Block.type.in_([*NAMED_NAV, "group"]), Block.is_active.is_(True))
    )
    errors = []
    for r in rows:
        name = nav_name(r.type, r.config)
        if name in names:
            errors.append({"field": f"{names[name]}.config", "message": f"이 틀을 쓰는 페이지({r.path})에 같은 이름의 탐색·랜드마크가 있습니다: {name}"})
    return errors
