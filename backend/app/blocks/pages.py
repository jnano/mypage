"""페이지 관리 — 홈블록 설계도 §3.5·§4.2·§4.6·§7·§11.

페이지는 주소·제목·설명·틀·열람 등급·색인 + 본문 블록 트리를 통째로 저장한다(If-Match 필수, 페이지 행 잠금).
주소 규칙(형식·예약 첫 단)은 app/blocks/routes 한 곳. 첫 화면('/')은 지울 수도 주소를 바꿀 수도 없다.
주소를 바꾸면 옛 주소를 page_path_history 에 남기고(페이지마다 최근 10개), 새 주소와 같은 옛 기록은 지운다(308 은 주소 집합이).
"""

from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.logs import LogEntry, record
from app.auth.viewer import Viewer
from app.blocks import tree
from app.blocks import types as t
from app.blocks.limits import MAX_PAGES, PATH_HISTORY_PER_PAGE
from app.blocks.menus import menus_using
from app.blocks.routes import is_page_path, reserved
from app.core.problems import Problem
from app.files import block_images
from app.models import Attachment, Block, Layout, Page, PagePathHistory


def _path(value: str) -> str:
    if not is_page_path(value):
        raise ValueError("주소는 / 또는 영문 소문자·숫자·하이픈으로 된 단(1~50자) 최대 3개입니다(예: /intro/history)")
    if reserved(value):
        raise ValueError("시스템이 쓰는 주소로 시작할 수 없습니다(예: /admin, /boards, /search)")
    return value


PagePath = Annotated[str, Field(max_length=160), AfterValidator(_path)]


class PageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: PagePath
    title: t.trimmed(1, 100)


class PageSave(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: PagePath
    title: t.trimmed(1, 100)
    description: t.trimmed(1, 300) | None = None
    layout_id: Annotated[int, Field(ge=1)] | None = None  # None = 사이트 기본 틀
    view_level: Annotated[int, Field(ge=0, le=99)] = 0
    indexable: bool = True
    blocks: list[tree.BlockIn] = []


def _not_found() -> Problem:
    return Problem(404, "page_not_found", "페이지를 찾을 수 없습니다")


def _path_taken() -> Problem:
    return Problem(409, "path_taken", "이미 쓰는 주소입니다")


PAGE_FIELDS = ("path", "title", "description", "layout_id", "view_level", "indexable")


def _page_out(page: Page) -> dict[str, Any]:
    return {
        "id": page.id, "path": page.path, "title": page.title, "description": page.description, "layout_id": page.layout_id,
        "status": page.status, "is_home": page.is_home, "view_level": page.view_level, "indexable": page.indexable,
        "version": page.version, "published_at": page.published_at, "content_updated_at": page.content_updated_at,
    }  # fmt: skip


async def page_detail(db: AsyncSession, page_id: int) -> dict[str, Any]:
    page = await db.get(Page, page_id)
    if page is None:
        raise _not_found()
    blocks = tree.nest(await tree.owner_blocks(db, "page", page_id)).get(None, [])
    history = (
        await db.execute(select(PagePathHistory.old_path).where(PagePathHistory.page_id == page_id).order_by(PagePathHistory.changed_at.desc()))
    ).scalars()
    return _page_out(page) | {"blocks": blocks, "old_paths": list(history)}


async def list_pages(db: AsyncSession) -> list[dict[str, Any]]:
    rows = await db.execute(
        select(Page.id, Page.path, Page.title, Page.status, Page.is_home, Page.view_level, Page.version, Page.updated_at).order_by(Page.path)
    )
    return [dict(r._mapping) for r in rows]


async def create_page(db: AsyncSession, viewer: Viewer, body: PageCreate) -> dict[str, Any]:
    if (await db.execute(select(func.count()).select_from(Page))).scalar_one() >= MAX_PAGES:
        raise Problem(409, "page_limit", f"페이지는 {MAX_PAGES}개까지입니다(주소 집합을 통째로 캐시한다 — §3.5)")
    page = Page(path=body.path, title=body.title, is_home=body.path == "/", updated_by=viewer.member_id)
    db.add(page)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise _path_taken() from None
    await db.execute(delete(PagePathHistory).where(PagePathHistory.old_path == body.path))  # 새 주소가 옛 기록을 가져간다
    await record(db, viewer, [LogEntry("page.create", "page", page.id, after={"path": page.path, "title": page.title})])
    return await page_detail(db, page.id)


async def layout_for(db: AsyncSession, layout_id: int | None) -> int | None:
    """페이지가 쓸 틀 — 고른 틀, 없으면 기본 틀(§3.3). 고른 틀이 없으면 422"""
    if layout_id is None:
        return (await db.execute(select(Layout.id).where(Layout.is_default))).scalar_one_or_none()
    if (await db.get(Layout, layout_id)) is None:
        raise tree.problem([{"field": "layout_id", "message": "없는 틀입니다"}], "dangling_ref")
    return layout_id


async def _move_path(db: AsyncSession, page: Page, new_path: str) -> None:
    """옛 주소를 남기고(같은 옛 주소가 다른 페이지의 기록이면 이 페이지로 옮겨 온다), 새 주소의 옛 기록은 지우고, 최근 10개만"""
    await db.execute(
        insert(PagePathHistory)
        .values(old_path=page.path, page_id=page.id)
        .on_conflict_do_update(index_elements=[PagePathHistory.old_path], set_={"page_id": page.id, "changed_at": func.now()})
    )
    await db.execute(delete(PagePathHistory).where(PagePathHistory.old_path == new_path))
    keep = (
        select(PagePathHistory.old_path)
        .where(PagePathHistory.page_id == page.id)
        .order_by(PagePathHistory.changed_at.desc(), PagePathHistory.old_path)
        .limit(PATH_HISTORY_PER_PAGE)
    )
    await db.execute(delete(PagePathHistory).where(PagePathHistory.page_id == page.id, PagePathHistory.old_path.not_in(keep)))


async def save_page(db: AsyncSession, viewer: Viewer, page_id: int, body: PageSave, expected_version: int) -> dict[str, Any]:
    page = await db.get(Page, page_id, with_for_update=True)  # 주인 행 잠금(§4.6)
    if page is None:
        raise _not_found()
    if page.version != expected_version:
        raise Problem(412, "version_conflict", "다른 사람이 먼저 고쳤습니다", headers={"ETag": f'"{page.version}"'})
    if page.is_home and body.path != "/":
        raise Problem(409, "home_page", "첫 화면(/)의 주소는 바꿀 수 없습니다")
    if not page.is_home and body.path == "/":
        raise Problem(409, "home_page", "첫 화면(/)은 하나뿐입니다")
    layout_id = await layout_for(db, body.layout_id)
    taken = await tree.nav_labels(db, layout_ids=[layout_id] if layout_id else [])
    try:
        flat = tree.validate_tree("page", [(None, body.blocks)], "blocks", taken)
    except tree.TreeErrors as e:
        raise tree.problem(e.errors) from None

    before = {k: getattr(page, k) for k in PAGE_FIELDS}
    if body.path != page.path:
        await _move_path(db, page, body.path)
    changed = await tree.save_tree(db, viewer.member_id, "page", page_id, flat)
    after = body.model_dump(include=set(PAGE_FIELDS))
    content_changed = before["title"] != after["title"] or any(changed.values())
    await db.execute(
        update(Page)
        .where(Page.id == page_id)
        .values(**after, version=Page.version + 1, updated_by=viewer.member_id, **({"content_updated_at": func.now()} if content_changed else {}))
    )
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise _path_taken() from None
    log_before = {k: v for k, v in before.items() if after[k] != v}
    log_after = {k: after[k] for k in log_before} | {k: v for k, v in changed.items() if v}
    await record(db, viewer, [LogEntry("page.update", "page", page_id, before=log_before or None, after=log_after or None)])
    if before["view_level"] != after["view_level"]:  # 열람 등급이 바뀌면 그림 공개 여부도(§4.7)
        await block_images.reconcile(db, await _block_ids(db, page_id))
    db.expire_all()
    return await page_detail(db, page_id)


async def _block_ids(db: AsyncSession, page_id: int) -> list[int]:
    return list((await db.execute(select(Block.id).where(Block.page_id == page_id))).scalars())  # post-clause: exempt — 블록 칸(글 아님)


async def set_status(db: AsyncSession, viewer: Viewer, page_id: int, published: bool) -> dict[str, Any]:
    """게시·비게시 — 처음 게시한 시각은 남긴다. 그림 공개 여부를 다시 맞춘다(비게시면 저장 순간 비공개 표시)"""
    page = await db.get(Page, page_id, with_for_update=True)
    if page is None:
        raise _not_found()
    status = "published" if published else "draft"
    if page.status != status:
        values: dict[str, Any] = {"status": status}
        if published and page.published_at is None:
            values["published_at"] = func.now()
        await db.execute(update(Page).where(Page.id == page_id).values(**values))
        await record(db, viewer, [LogEntry("page.publish" if published else "page.unpublish", "page", page_id, before={"status": page.status}, after={"status": status})])
        await block_images.reconcile(db, await _block_ids(db, page_id))
    db.expire_all()
    return await page_detail(db, page_id)


async def delete_page(db: AsyncSession, viewer: Viewer, page_id: int) -> None:
    """블록·옛 주소는 함께(CASCADE), 블록 그림은 임시로 — 지우기 전에 비공개로. 메뉴가 가리키면 409(§11)"""
    page = await db.get(Page, page_id, with_for_update=True)
    if page is None:
        raise _not_found()
    if page.is_home:
        raise Problem(409, "home_page", "첫 화면(/) 페이지는 지울 수 없습니다")
    if in_menu := await menus_using(db, page_id=page_id):
        raise Problem(
            409, "in_menu", "메뉴에 있는 페이지입니다. 먼저 메뉴에서 빼세요",
            errors=[{"field": f"menu_items.{i}", "message": "이 메뉴 항목이 가리킵니다"} for i in in_menu],
        )  # fmt: skip
    images = select(Attachment.id).join(Block, Block.id == Attachment.block_id).where(Block.page_id == page_id)  # post-clause: exempt — 첨부 칸(글 아님)
    await block_images.release(db, (await db.execute(images)).scalars())
    await record(db, viewer, [LogEntry("page.delete", "page", page_id, before={"path": page.path, "title": page.title})])
    try:
        await db.execute(delete(Page).where(Page.id == page_id))
    except IntegrityError:  # 확인과 지우기 사이에 메뉴가 이 페이지를 가리켰다(FK RESTRICT) — 500 이 아니라 409(코드 검토 v6 N-3)
        await db.rollback()
        raise Problem(409, "in_menu", "메뉴에 있는 페이지입니다. 먼저 메뉴에서 빼세요") from None


async def reserved_conflicts(db: AsyncSession) -> list[dict[str, Any]]:
    """예약 첫 단과 겹친 페이지 — 새 라우트 배포로 예약어가 늘면 그 페이지는 라우트에 가려진다(§11, 검토 N-5). 페이지 ≤ 1,000"""
    rows = await db.execute(select(Page.id, Page.path))
    return [{"id": r.id, "path": r.path} for r in rows if reserved(r.path)]


async def public_paths(db: AsyncSession) -> dict[str, Any]:
    """주소 집합(GET /api/pages/paths, §5.5) — 게시된 페이지 주소(personal = 열람 등급 > 0 — 주소가 있다는 것만, 제목·내용은
    알리지 않는다)와 옛 주소 → 새 주소(게시된 페이지만). 초안은 없다. 페이지 1,000 + 옛 주소 10씩이라 100KB 안팎"""
    pages = {
        r.path: {"id": r.id, "personal": r.view_level > 0}
        for r in await db.execute(select(Page.id, Page.path, Page.view_level).where(Page.status == "published"))
    }
    moved = {
        r.old_path: r.path
        for r in await db.execute(
            select(PagePathHistory.old_path, Page.path).join(Page, Page.id == PagePathHistory.page_id).where(Page.status == "published")
        )
    }
    return {"pages": pages, "moved": moved, "cache": {"tags": ["pages:paths"]}}


async def sitemap_pages(db: AsyncSession) -> list[dict[str, Any]]:
    """sitemap 의 사용자 페이지(본 §10) — 게시 ∧ 열람 등급 0 ∧ 색인 허용. lastmod = content_updated_at ?? published_at"""
    rows = await db.execute(
        select(Page.path, func.coalesce(Page.content_updated_at, Page.published_at).label("lastmod"))
        .where(Page.status == "published", Page.view_level == 0, Page.indexable.is_(True))
        .order_by(Page.path)
    )
    return [{"path": r.path, "lastmod": r.lastmod.isoformat() if r.lastmod else None} for r in rows]
