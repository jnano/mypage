"""틀 묶음 — 홈블록 설계도 §5.2·§5.3·§5.5·§6.1.

공개 GET /api/frame 은 **언제나 비회원 기준**이다(보는 사람을 읽지 않는다 — B-2). 쿼리는 묶음 하나당 8개 이하:
① 주인 고르기 ② 블록 ③ 메뉴 항목 ④ 참조 게시판·페이지 ⑤ 최근 글·고정 글 ⑥ 최근 댓글 ⑦ 블록 그림 ⑧ 사이트 이름.
블록마다 쿼리하지 않는다 — 같은 종류를 모아 한 번에 읽고 블록별로 나눈다(P2).

보이기(§6.1): 숨긴 블록은 없다. 회원 대상·등급 조건 블록, 비회원이 열 수 없는 게시판을 고른 동적 블록은 '개인 블록' —
내용 없이 자리(id)만 싣고 page-state 가 보는 사람 기준으로 채운다(걸음 5-3). 보는 사람에 따라 결과가 달라지는
블록(등급 메뉴 항목, 비회원에게 안 보이는 게시판·페이지로 가는 링크)은 비회원용 내용을 싣고 '회원이면 다시'로 표시한다.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from pydantic import ValidationError
from sqlalchemy import BigInteger, Integer, column, func, literal, literal_column, not_, or_, select, true, union_all, values
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.admin import settings as site_settings
from app.auth.viewer import GUEST, Viewer
from app.blocks import resolve as r
from app.blocks import types as t
from app.blocks.menus import ITEM_COLUMNS
from app.blocks.limits import RECENT_COMMENT_POSTS
from app.blocks.tree import BLOCK_COLUMNS, Refs, collect_refs
from app.core.threads import run_in_thread
from app.editor.render import ImageSource
from app.files.attach import ROW_COLUMNS, image_sources, thumb_template
from app.models import Attachment, Block, Board, Comment, Layout, LayoutBinding, MenuItem, Page, PagePathHistory, Post, SiteSetting
from app.permissions import (
    block_view,
    guest_readable_boards_clause,
    listable_boards_clause,
    listable_posts_clause,
    page_read,
    readable_posts_clause,
)

log = logging.getLogger(__name__)

PUBLISHED = literal_column("'published'")
TRUE = literal_column("true")
FALSE = literal_column("false")
DYNAMIC = ("recent_posts", "recent_comments", "board_links")
EXCERPT = 80


@dataclass
class Node:
    row: Any
    model: Any
    refs: Refs
    children: list["Node"] = field(default_factory=list)
    personal: bool = False  # 내용 없이 자리만(page-state 가 채운다)
    refresh: bool = False  # 비회원용 내용 + 회원이면 다시


def _seo_value():
    """사이트 설정 seo 원문(JSONB) — 주인 고르기 문장에 함께 실어 쿼리 하나를 줄인다(걸음 8 결정 ⑨: 개인 틀 9 → 8)"""
    return select(SiteSetting.value).where(SiteSetting.key == literal_column("'seo'")).scalar_subquery().label("seo")


async def _owner(db: AsyncSession, board_slug: str | None, route: str | None) -> Any:
    """① 주인 고르기 — 게시판의 틀 → 화면 종류의 틀 → 기본 틀(§3.3). 한 문장"""
    default = select(Layout.id).where(Layout.is_default).scalar_subquery()
    candidates = []
    if board_slug is not None:
        candidates.append(select(Board.layout_id).where(Board.slug == board_slug).scalar_subquery())
    route_class = "board" if board_slug is not None else route
    if route_class is not None:
        candidates.append(select(LayoutBinding.layout_id).where(LayoutBinding.route_class == route_class).scalar_subquery())
    chosen = func.coalesce(*candidates, default)
    return (await db.execute(select(Layout.id, Layout.version, _seo_value()).where(Layout.id == chosen))).one_or_none()


def _tree(rows: Sequence[Any]) -> dict[str, list[Node]]:
    """블록 행 → 영역마다 노드 트리. 숨긴 블록은 가지째 뺀다. 저장 뒤 형식이 바뀌어 검증되지 않는 설정은 건너뛴다(경고)"""
    nodes: dict[int, Node] = {}
    for row in rows:
        if not row.is_active:
            continue
        try:
            model = t.validate_config(row.type, row.config)
        except (ValidationError, t.UnknownBlockType):
            log.warning("블록 %s(%s) 설정이 지금 형식과 맞지 않아 건너뜀", row.id, row.type)
            continue
        nodes[row.id] = Node(row, model, collect_refs(model))
    regions: dict[str, list[Node]] = {}
    for row in sorted(rows, key=lambda x: (x.sort_order, x.id)):
        node = nodes.get(row.id)
        if node is None:
            continue
        if row.parent_id is None:
            regions.setdefault(row.region, []).append(node)
        elif (parent := nodes.get(row.parent_id)) is not None:
            parent.children.append(node)
    return regions


def _walk(nodes: Sequence[Node]):
    for n in nodes:
        yield n
        yield from _walk(n.children)


async def _menus(db: AsyncSession, menu_ids: set[int]) -> dict[int, list[Any]]:
    """③ 메뉴 항목"""
    out: dict[int, list[Any]] = {i: [] for i in menu_ids}
    if menu_ids:
        for row in await db.execute(select(MenuItem.menu_id, *ITEM_COLUMNS).where(MenuItem.menu_id.in_(menu_ids))):  # post-clause: exempt — 메뉴 항목 칸(글 아님)
            out[row.menu_id].append(row)
    return out


@dataclass
class Targets:
    boards: dict[int, Any] = field(default_factory=dict)  # id → (slug, name, listable, readable, last_posted_at)
    pages: dict[int, str] = field(default_factory=dict)  # 비회원에게 보이는 페이지 id → 주소


async def _targets(db: AsyncSession, board_ids: set[int], page_ids: set[int], viewer: Viewer = GUEST) -> Targets:
    """④ 참조 게시판·페이지 — 한 문장(UNION ALL). 게시판은 목록·열람 가능 여부와 최근 글 시각(게시판 바로가기).
    목록 판정은 보는 사람 기준 절(listable_boards_clause — 명부·담당 EXISTS 포함)로 같은 문장 안에서(코드 검토 v12 N-1)"""
    parts = []
    if board_ids:
        last = (
            select(Post.published_at)
            .where(Post.board_id == Board.id, listable_posts_clause(viewer), Post.is_pinned == FALSE)
            .order_by(Post.published_at.desc(), Post.id.desc())
            .limit(1)
            .correlate(Board)
            .scalar_subquery()
        )
        parts.append(
            select(
                literal("board").label("kind"), Board.id, Board.slug.label("key"), Board.name,
                listable_boards_clause(viewer).label("listable"), guest_readable_boards_clause().label("readable"),
                last.label("last_posted_at"),
            ).where(Board.id.in_(board_ids))
        )  # fmt: skip
    if page_ids:
        public = (Page.status == PUBLISHED) & (Page.view_level <= viewer.level)
        parts.append(
            select(
                literal("page").label("kind"), Page.id, Page.path.label("key"), Page.title.label("name"),
                public.label("listable"), public.label("readable"), literal(None).label("last_posted_at"),
            ).where(Page.id.in_(page_ids))
        )  # fmt: skip
    out = Targets()
    if not parts:
        return out
    rows = list(await db.execute(union_all(*parts) if len(parts) > 1 else parts[0]))
    for row in rows:
        if row.kind == "board":
            # readable 은 비회원 기준(공개 묶음의 개인 블록 판정용) — 회원 경로의 글 판정은 readable_posts_clause(viewer)(코드 검토 v9 N-2)
            out.boards[row.id] = SimpleNamespace(key=row.key, name=row.name, listable=row.listable, readable=row.readable, last_posted_at=row.last_posted_at)
        elif row.listable:
            out.pages[row.id] = row.key
    return out


def _decide(nodes: Sequence[Node], menus: dict[int, list[Any]], targets: Targets) -> None:
    """비회원 기준으로 블록마다 공개·개인·회원이면 다시를 정한다(§6.1). 부모가 개인이면 가지째 개인"""
    listable = {i for i, b in targets.boards.items() if b.listable}
    readable = {i for i, b in targets.boards.items() if b.readable}
    for n in nodes:
        row = n.row
        if not block_view(GUEST, row):  # 회원 대상·등급 조건 — 회원 블록과 같은 판정 한 곳(permissions.block_view)
            n.personal = True
        elif row.type in ("recent_posts", "recent_comments"):
            n.personal = not n.refs.boards <= readable  # 회원 전용 게시판의 글이 공개 캐시에 섞이지 않게(P1)
        elif row.type in ("board_links", "module"):  # 게시판 모듈: 비회원이 목록을 못 보는 게시판이면 자리만(회원이면 그 사람 기준으로)
            n.personal = not n.refs.boards <= listable
        else:
            menu_rows = [i for m in n.refs.menus for i in menus.get(m, [])]
            hidden_link = (n.refs.boards - listable) or (n.refs.pages - set(targets.pages))
            varies = any(
                i.min_level > 0
                or (i.link_kind == "board" and i.board_id not in listable)
                or (i.link_kind == "page" and i.page_id not in targets.pages)
                for i in menu_rows
            )
            n.refresh = bool(hidden_link or varies)
        if n.personal:
            for c in _walk(n.children):
                c.personal = True


def _recent_targets(nodes: Sequence[Node], block_type: str) -> dict[int, int]:
    """게시판 id → 그 게시판을 고른 블록들의 개수 최댓값(n)"""
    out: dict[int, int] = {}
    for n in nodes:
        if n.row.type == block_type and not n.personal:
            for b in n.refs.boards:
                out[b] = max(out.get(b, 0), n.model.count)
    return out


def _values(targets: dict[int, int]):
    return values(column("bid", BigInteger), column("n", Integer), name="t").data(sorted(targets.items()))


def _not_expired():
    return or_(Post.expires_at.is_(None), Post.expires_at > func.now())


async def _recent_posts(db: AsyncSession, targets: dict[int, int], pinned: bool, viewer: Viewer = GUEST) -> list[Any]:
    return list(await db.execute(recent_posts_statement(targets, pinned, viewer))) if targets else []


def recent_posts_statement(targets: dict[int, int], pinned: bool, viewer: Viewer = GUEST):
    """⑤ 최근 글 + 고정 글 — 게시판마다 LATERAL(공개 판정·만료 거르기는 LIMIT 앞, 검토 N-2). 한 문장.
    실행과 측정(scripts/explain_hotpaths.py)이 같은 문장을 쓴다"""
    t_ = _values(targets)

    def branch(is_pinned: bool):
        order = (Post.pin_order.asc().nulls_last(), Post.published_at.desc(), Post.id.desc()) if is_pinned else (Post.published_at.desc(), Post.id.desc())
        sub = (
            select(Post.id, Post.board_id, Post.title, Post.published_at, Post.is_pinned, Post.pin_order)
            .where(Post.board_id == t_.c.bid, readable_posts_clause(viewer), _not_expired(), Post.is_pinned == (TRUE if is_pinned else FALSE))
            .order_by(*order)
            .limit(t_.c.n)
            .lateral("p")
        )
        return select(sub).select_from(t_).join(sub, true())

    posts = union_all(branch(False), branch(True)).subquery("posts") if pinned else branch(False).subquery("posts")
    cover = (
        select(Attachment.id.label("cover_id"), Attachment.storage_key, Attachment.visibility, Attachment.is_image,
               Attachment.width, Attachment.height, Attachment.thumbs_ready)  # fmt: skip
        .where(Attachment.post_id == posts.c.id, Attachment.is_cover.is_(True))
        .limit(1)
        .lateral("cover")
    )
    return select(posts, cover).select_from(posts).outerjoin(cover, true())


async def _recent_comments(db: AsyncSession, targets: dict[int, int], viewer: Viewer = GUEST) -> list[Any]:
    return list(await db.execute(recent_comments_statement(targets, viewer=viewer))) if targets else []


def recent_comments_statement(targets: dict[int, int], posts_per_board: int = RECENT_COMMENT_POSTS, viewer: Viewer = GUEST):
    """⑥ 최근 댓글 — 게시판마다 그 게시판의 최근 글(고정 글 포함) posts_per_board 개를 목록 인덱스로 고르고, 그 글들의
    최신 댓글을 글별 댓글 인덱스(ix_comments_post)로 모은다. 댓글이 드문 게시판도 훑는 양에 상한이 있다(M-1 측정 —
    전역 '최신 댓글' 인덱스를 거꾸로 훑으면 댓글 없는 게시판에서 수백 ms). 그래서 아주 오래된 글에 새로 달린 댓글은
    블록에 나오지 않는다(§5.2 M-1 결정). 실행과 측정(scripts/explain_hotpaths.py)이 같은 문장을 쓴다"""
    t_ = _values(targets)

    def board_posts(is_pinned: bool):
        order = (Post.pin_order.asc().nulls_last(),) if is_pinned else (Post.published_at.desc(), Post.id.desc())
        return (
            select(Post.id, Post.title)
            .where(Post.board_id == t_.c.bid, readable_posts_clause(viewer), _not_expired(), Post.is_pinned == (TRUE if is_pinned else FALSE))
            .order_by(*order)
            .limit(posts_per_board)
            .correlate(t_)  # 바깥 LATERAL 의 게시판(t.bid)에 묶는다 — 없으면 값 목록을 따로 또 읽어 모든 게시판의 글을 본다
        )

    recent_posts = union_all(board_posts(False), board_posts(True)).subquery("rp")
    per_post = (
        select(Comment.id, Comment.post_id, Comment.content, Comment.created_at, Comment.author_name_snapshot)
        .where(Comment.post_id == recent_posts.c.id, Comment.status == PUBLISHED, not_(Comment.is_blinded))
        .order_by(Comment.created_at.desc(), Comment.id.desc())
        .limit(t_.c.n)
        .lateral("pc")
    )
    sub = (
        select(per_post, t_.c.bid.label("board_id"), recent_posts.c.title.label("post_title"))
        .select_from(recent_posts)
        .join(per_post, true())
        .order_by(per_post.c.created_at.desc(), per_post.c.id.desc())
        .limit(t_.c.n)
        .lateral("c")
    )
    return select(sub).select_from(t_).join(sub, true())


_IMAGE_FIELDS = ("id", "post_id", "block_id", "uploader_id", "role", "storage_key", "visibility", "is_image", "width", "height", "thumbs_ready")


def _images_column():
    """블록 행에 그 블록의 그림 첨부를 JSON 배열로 함께 싣는다(ix_attachments_block) — 그림 쿼리를 따로 하지 않아 묶음 쿼리 하나를
    줄인다(걸음 8 결정 ⑨: 개인 틀이 보는 사람 조회·요청 수 세기까지 ≤ 8). 칸은 files.attach.ROW_COLUMNS 와 같다"""
    a = aliased(Attachment, name="blk_att")
    obj = func.json_build_object(*[x for name in _IMAGE_FIELDS for x in (literal_column(f"'{name}'"), getattr(a, name))])
    return (
        select(func.coalesce(func.json_agg(obj), literal_column("'[]'::json")))
        .where(a.block_id == Block.id)
        .correlate(Block)
        .scalar_subquery()
        .label("images")
    )


def _image_rows(rows: Sequence[Any], keep: set[int]) -> list[Any]:
    """블록 행에 실린 그림 → 첨부 행 모양(image_sources·thumb_template 가 읽는 칸)"""
    return [SimpleNamespace(**img) for row in rows if row.id in keep for img in (row.images or [])]


async def _images(db: AsyncSession, block_ids: set[int]) -> list[Any]:
    """그림 따로 읽기 — 그림을 블록 행에 싣지 않는 길(회원 블록 호출)"""
    if not block_ids:
        return []
    return list(await db.execute(select(*ROW_COLUMNS, Attachment.block_id).where(Attachment.block_id.in_(block_ids))))  # post-clause: exempt — 첨부 칸(글 아님)


async def _images_by_id(db: AsyncSession, ids: set[int]) -> list[Any]:
    """미리보기의 ⑦ — 설정이 가리키는 그림 첨부(저장 전이라 block_id 로 찾을 수 없다). 운영자 전용 경로에서만 부른다.
    운영자는 모든 첨부를 받을 수 있으므로 남이 올린 임시 그림이 보여도 새는 것이 아니다 — 저장 때 save_tree 가 다시 판정한다"""
    if not ids:
        return []
    # 글의 첨부는 빼고(블록 저장도 거부한다), 그림만
    return list(await db.execute(select(*ROW_COLUMNS).where(Attachment.id.in_(ids), Attachment.post_id.is_(None), Attachment.is_image == TRUE)))  # post-clause: exempt — 첨부 칸(글 아님)


def _excerpt(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= EXCERPT else text[: EXCERPT - 1] + "…"


def _dynamic_view(n: Node, targets: Targets, posts: Sequence[Any], comments: Sequence[Any]) -> r.View | None:
    m = n.model
    boards = [b for b in m.board_ids if b in targets.boards]
    slug = {b: targets.boards[b].key for b in boards}
    if isinstance(m, t.BoardLinks):
        boards = [b for b in boards if targets.boards[b].listable]  # 보는 사람이 목록을 볼 수 있는 게시판만
        items = [{"name": targets.boards[b].name, "href": f"/boards/{slug[b]}", "last_posted_at": targets.boards[b].last_posted_at} for b in boards]
        return {"title": m.title, "items": items} if items else None
    if isinstance(m, t.RecentPosts):
        mine = [p for p in posts if p.board_id in slug]
        pinned = []
        if m.include_pinned:  # 고른 게시판 순서, 그 안에서 pin_order 순 — 앞에 둔다(§4.4)
            for b in boards:
                pinned += [p for p in mine if p.is_pinned and p.board_id == b]
        recent = sorted((p for p in mine if not p.is_pinned), key=lambda p: (p.published_at, p.id), reverse=True)
        chosen = (pinned + recent)[: m.count]
        items = []
        for p in chosen:
            item = {"id": p.id, "title": p.title, "href": f"/boards/{slug[p.board_id]}/{p.id}", "published_at": p.published_at, "pinned": p.is_pinned}
            if m.view == "photo":  # 대표 사진 — 없으면 화면이 자리 표시를 그린다(§4.4). 제목이 이름이라 그림은 장식(빈 alt)
                cover = SimpleNamespace(id=p.cover_id, storage_key=p.storage_key, visibility=p.visibility)
                item["image"] = r.image_view(ImageSource(thumb_template(cover), p.width, p.height, p.thumbs_ready), "") if p.cover_id else None
            items.append(item)
        return {"title": m.title, "view": m.view, "items": items}
    if isinstance(m, t.RecentComments):
        mine = sorted((c for c in comments if c.board_id in slug), key=lambda c: (c.created_at, c.id), reverse=True)[: m.count]
        items = [
            {"id": c.id, "excerpt": _excerpt(c.content), "author": c.author_name_snapshot, "post_title": c.post_title,
             "href": f"/boards/{slug[c.board_id]}/{c.post_id}#c-{c.id}", "created_at": c.created_at}  # fmt: skip
            for c in mine
        ]
        return {"title": m.title, "items": items}
    return None


def _out(n: Node, lookup: r.Lookup, targets: Targets, posts: Sequence[Any], comments: Sequence[Any], personal: list[int], images: dict[int, list[int]]) -> r.View | None:
    base: r.View = {"id": n.row.id, "type": n.row.type}
    if n.row.audience == "guest":
        base["audience"] = "guest"  # 로그인했으면 화면이 세션 쿠키로 숨긴다(표시용 — 공개 정보, §6.1)
    if n.personal:
        personal.append(n.row.id)
        return base | {"personal": True}
    if n.row.type in DYNAMIC:
        data = _dynamic_view(n, targets, posts, comments)
    else:
        data = r.resolve(n.row.type, n.model, lookup, attachment_ids=images.get(n.row.id, ()))
    if data is None:
        return None
    out = base | {"data": data}
    if n.refresh:
        personal.append(n.row.id)
        out["refresh"] = True
    if n.children:
        kids = [(c, _out(c, lookup, targets, posts, comments, personal, images)) for c in n.children]
        if n.row.type == "columns":
            cols: list[list[r.View]] = [[] for _ in range(n.model.count)]
            for c, v in kids:
                if v is not None and c.row.column_index is not None and c.row.column_index < n.model.count:
                    cols[c.row.column_index].append(v)
            out["columns"] = cols
        else:
            out["children"] = [v for _, v in kids if v is not None]
    return out


@dataclass
class Owner:
    layout_id: int | None
    layout_version: int | None
    page: Any | None = None  # 페이지 행(사용자 페이지일 때)
    seo: Any | None = None  # 주인 고르기 문장이 함께 읽은 설정 seo 원문(행이 없으면 None — 기본값)
    seo_loaded: bool = False


PAGE_COLUMNS = (
    Page.id, Page.path, Page.title, Page.description, Page.layout_id, Page.status, Page.view_level, Page.indexable,
    Page.version, Page.published_at, Page.content_updated_at,
)  # fmt: skip


class PageNotFound(Exception):
    """게시되지 않았거나(공개) 볼 수 없는 주소 — moved 가 있으면 옛 주소(308)"""

    def __init__(self, moved: str | None = None):
        self.moved = moved


async def _page_owner(db: AsyncSession, path: str, viewer: Viewer, draft: bool) -> Owner:
    """① 주인 고르기(페이지) — 페이지 + 그 틀(페이지의 틀 → 기본 틀) 한 문장. 공개는 게시 ∧ 열람 등급 0, 개인은 page.read,
    draft 는 운영자만 상태와 무관하게. 없으면 옛 주소를 한 번 더 본다(없는 주소일 때만 — 정상 흐름은 Next 의 주소 집합이 먼저 거른다)"""
    conds = [Page.path == path]
    if not (draft and viewer.is_admin):
        conds.append(Page.status == PUBLISHED)
        conds.append(Page.view_level <= (0 if viewer.member_id is None else viewer.level) if not viewer.is_admin else true())
    page = select(*PAGE_COLUMNS).where(*conds).subquery("pg")  # post-clause: exempt — 페이지 칸(글 아님)
    default = select(Layout.id).where(Layout.is_default).scalar_subquery()
    row = (
        await db.execute(select(page, Layout.id.label("lid"), Layout.version.label("lversion"), _seo_value()).select_from(page).outerjoin(Layout, Layout.id == func.coalesce(page.c.layout_id, default)))
    ).one_or_none()
    if row is None:
        moved = (
            await db.execute(
                select(Page.path).join(PagePathHistory, PagePathHistory.page_id == Page.id).where(PagePathHistory.old_path == path, Page.status == PUBLISHED)
            )
        ).scalar_one_or_none()
        raise PageNotFound(moved)
    return Owner(row.lid, row.lversion, row, seo=row.seo, seo_loaded=True)


async def _route_owner(db: AsyncSession, board_slug: str | None, route: str | None) -> Owner:
    row = await _owner(db, board_slug, route)
    return Owner(row.id, row.version, seo=row.seo, seo_loaded=True) if row is not None else Owner(None, None)


async def _blocks(db: AsyncSession, owner: Owner) -> list[Any]:
    """② 블록 — 틀의 블록 ∪ 페이지 본문 블록(부분 인덱스 둘의 BitmapOr, §5.2)"""
    conds = []
    if owner.layout_id is not None:
        conds.append(Block.layout_id == owner.layout_id)
    if owner.page is not None:
        conds.append(Block.page_id == owner.page.id)
    if not conds:
        return []
    return list(await db.execute(select(*BLOCK_COLUMNS, _images_column()).where(or_(*conds))))  # post-clause: exempt — 블록 칸(글 아님)


def _prune(nodes: list[Node], viewer: Viewer) -> list[Node]:
    """보는 사람 기준 묶음 — 못 보는 블록은 가지째 뺀다(block.view, 부모가 안 보이면 자식도 — §6.1)"""
    out = []
    for n in nodes:
        if block_view(viewer, n.row):
            n.children = _prune(n.children, viewer)
            out.append(n)
    return out


async def _views(db: AsyncSession, viewer: Viewer, rows: Sequence[Any], *, preview: bool = False, owner: "Owner | None" = None):
    """블록 행 → 영역마다 그릴 모양. 묶음 응답과 관리 화면 미리보기가 함께 쓴다. preview 면 그림을 블록에 붙은 것이 아니라
    설정이 가리키는 첨부 id 로 찾는다(저장 전 — 아직 block_id 가 없다)"""
    public = viewer.member_id is None
    regions = _tree(rows)  # ②
    if not public:
        regions = {k: _prune(v, viewer) for k, v in regions.items()}
    nodes = [n for top in regions.values() for n in _walk(top)]
    refs = Refs()
    for n in nodes:
        refs.boards |= n.refs.boards
        refs.pages |= n.refs.pages
        refs.menus |= n.refs.menus
    menus = await _menus(db, refs.menus)  # ③
    for items in menus.values():  # 이름이 rows 면 블록 행(인자)을 덮는다
        refs.boards |= {i.board_id for i in items if i.link_kind == "board"}
        refs.pages |= {i.page_id for i in items if i.link_kind == "page"}
    targets = await _targets(db, refs.boards, refs.pages, viewer)  # ④
    if public:
        _decide(nodes, menus, targets)
    post_targets = _recent_targets(nodes, "recent_posts")
    pinned = any(n.row.type == "recent_posts" and not n.personal and n.model.include_pinned for n in nodes)
    posts = await _recent_posts(db, post_targets, pinned, viewer)  # ⑤
    comments = await _recent_comments(db, _recent_targets(nodes, "recent_comments"), viewer)  # ⑥
    if preview:
        image_rows = await _images_by_id(db, {a for n in nodes if not n.personal for a in n.refs.attachments})  # ⑦
    elif rows and hasattr(rows[0], "images"):  # ② 블록 문장이 함께 실었다
        image_rows = _image_rows(rows, {n.row.id for n in nodes if not n.personal})
    else:
        image_rows = await _images(db, {n.row.id for n in nodes if not n.personal})  # ⑦
    if owner is not None and owner.seo_loaded:  # ⑧ — 주인 고르기 문장(①)이 이미 읽었다
        seo = site_settings.SeoSettings.model_validate(owner.seo) if owner.seo is not None else site_settings.SeoSettings()
    else:
        seo = await site_settings.load(db, "seo")  # ⑧
    assert isinstance(seo, site_settings.SeoSettings)

    images: dict[int, list[int]] = {}
    if preview:
        found = {row.id for row in image_rows}
        images = {n.row.id: sorted(n.refs.attachments & found) for n in nodes}
    else:
        for row in image_rows:
            images.setdefault(row.block_id, []).append(row.id)
    lookup = r.Lookup(
        site_name=seo.site_name,
        page_paths=targets.pages,
        board_slugs={i: b.key for i, b in targets.boards.items() if b.listable},
        images=image_sources(image_rows),
        menus=menus,
        viewer_level=viewer.level,
    )

    def assemble() -> tuple[dict[str | None, list[r.View]], list[int]]:
        personal: list[int] = []
        out: dict[str | None, list[r.View]] = {}
        for region in (*t.REGIONS, None):
            views = [v for n in regions.get(region, []) if (v := _out(n, lookup, targets, posts, comments, personal, images)) is not None]
            if views:
                out[region] = views
        return out, personal

    # 마크다운 변환·정화는 CPU 작업 — 이벤트 루프가 아니라 정화 스레드 한도 안에서(글 저장과 같은 한도, 코드 검토 v5 N-2)
    out, personal = await run_in_thread("sanitize", assemble)
    return out, personal, refs, nodes, post_targets


async def _bundle(db: AsyncSession, viewer: Viewer, owner: Owner, tags: list[str]) -> dict[str, Any]:
    """비회원(공개 캐시)이면 개인 블록은 자리만·회원이면 다시(_decide), 보는 사람 기준(개인 틀)이면 못 보는 블록을 빼고
    모두 그 사람 기준으로 푼다. 쿼리 ≤ 8(§12, 공개 묶음·개인 틀 같음): 주인·블록·메뉴·대상·글·댓글·그림·설정 —
    명부·담당은 대상 문장 안의 EXISTS 라 따로 세지 않는다(코드 검토 v12 N-1)"""
    out, personal, refs, nodes, post_targets = await _views(db, viewer, await _blocks(db, owner), owner=owner)  # ②~⑦(⑧은 ①이 함께)
    tags += [f"menu:{m}" for m in sorted(refs.menus)]
    if refs.boards:
        tags.append("boards:structure")
    if post_targets:
        tags.append("recent:posts")
    if any(n.row.type == "recent_comments" and not n.personal for n in nodes):
        tags.append("recent:comments")
    page_out = None
    if owner.page is not None:
        p = owner.page
        page_out = {
            "id": p.id, "path": p.path, "title": p.title, "description": p.description, "indexable": p.indexable,
            "view_level": p.view_level, "published_at": p.published_at, "content_updated_at": p.content_updated_at,
            "draft": p.status != "published", "blocks": out.pop(None, []),
        }  # fmt: skip
    out.pop(None, None)
    layout = None if owner.layout_id is None else {"id": owner.layout_id, "version": owner.layout_version, "regions": out}
    return {"layout": layout, "page": page_out, "personal_block_ids": personal, "cache": {"tags": sorted(set(tags))}}


async def frame_bundle(db: AsyncSession, *, board_slug: str | None = None, route: str | None = None, path: str | None = None) -> dict[str, Any]:
    """공개 틀 묶음(GET /api/frame) — 언제나 비회원 기준(B-2). path 면 게시 ∧ 열람 등급 0 페이지만(아니면 PageNotFound)"""
    tags = ["layouts:bindings", "settings:seo"]
    if board_slug is not None:
        tags.append("boards:structure")  # 게시판의 틀(boards.layout_id) 바꾸기는 board.updated 가 이 태그를 즉시 만료한다
    if path is not None:
        owner = await _page_owner(db, path, GUEST, draft=False)  # ①
        tags += [f"page:{owner.page.id}", "pages:paths"]  # 정지점 N-1 ①
    else:
        owner = await _route_owner(db, board_slug, route)  # ①
    if owner.layout_id is not None:
        tags.append(f"layout:{owner.layout_id}")
    if owner.layout_id is None and owner.page is None:  # 틀이 하나도 없다 — 화면이 코드의 대체 틀을 쓴다(§3.6)
        return {"layout": None, "page": None, "personal_block_ids": [], "cache": {"tags": tags}}
    return await _bundle(db, GUEST, owner, tags)


async def viewer_frame(db: AsyncSession, viewer: Viewer, path: str, *, draft: bool) -> dict[str, Any]:
    """개인 틀(GET /api/me/frame) — 열람 등급 페이지(§6.2)·운영자의 초안 보기(§5.5). 보는 사람 기준으로 통째로 푼다.
    캐시하지 않는다. draft 는 운영자만(아니면 없는 주소와 같은 404)"""
    if draft and not viewer.is_admin:
        raise PageNotFound()
    owner = await _page_owner(db, path, viewer, draft=draft)
    return await _bundle(db, viewer, owner, [])


async def preview(db: AsyncSession, viewer: Viewer, flat: Sequence[Any], *, as_member: bool) -> dict[str, Any]:
    """관리 화면 미리보기(POST /api/admin/blocks/preview, §8) — 검증을 마친 저장 전 트리(tree.validate_tree 결과)를 그릴 모양으로.
    as_member=False 면 비회원이 보는 모습(회원 블록은 자리만 — personal), True 면 이 운영자 기준. 아무것도 저장하지 않는다.
    새 블록에는 id 가 없어 음수 임시 id 를 준다(응답 안에서만 쓰는 이름)"""
    ids: dict[int, int] = {}
    rows = []
    for i, b in enumerate(flat):
        ids[id(b)] = b.item.id if b.item.id is not None else -(i + 1)
    for b in flat:
        rows.append(SimpleNamespace(
            id=ids[id(b)], parent_id=ids[id(b.parent)] if b.parent is not None else None, region=b.region,
            column_index=b.item.column_index, sort_order=b.sort_order, type=b.item.type, config=b.config,
            audience=b.item.audience, min_level=b.item.min_level, is_active=b.item.is_active,
        ))  # fmt: skip
    out, personal, *_ = await _views(db, viewer if as_member else GUEST, rows, preview=True)
    return {"regions": {k: v for k, v in out.items() if k is not None}, "blocks": out.get(None, []), "personal_block_ids": personal}


# ── 회원 블록(걸음 5-3) — GET /api/me/page-state?blocks= ─────────────────────
# 공개 묶음의 personal_block_ids(내용 없는 자리·회원이면 다시)를 보는 사람 기준으로 채운다(§5.4). 블록 id 는 비밀이 아니므로
# 주인이 지금 화면 것인지 따지지 않고, 블록마다 보이기(block.view)와 데이터를 이 사람 기준으로 다시 판정한다 — 못 보는
# 블록은 응답에 없다(빈 값이 아니라 없음). 쿼리는 공개 묶음과 같은 방식으로 모아서 ≤ 8(블록·메뉴·대상·글·댓글·그림·이름)

MAX_PERSONAL_BLOCKS = 30


async def personal_blocks(db: AsyncSession, viewer: Viewer, block_ids: Sequence[int]) -> dict[int, r.View]:
    ids = sorted(set(block_ids))[:MAX_PERSONAL_BLOCKS]
    if not ids:
        return {}
    rows = list(  # ① 요청한 블록 + 그 자식(묶음·칸 나누기)
        await db.execute(
            # 주인이 페이지면 page.read 를 같은 문장에서(쿼리 수 그대로 — 코드 검토 v9 N-1, 정지점 N-1)
            select(*BLOCK_COLUMNS, Block.layout_id, Block.page_id, Page.status.label("page_status"), Page.view_level.label("page_view_level"))  # post-clause: exempt — 블록·페이지 칸(글 아님)
            .outerjoin(Page, Page.id == Block.page_id)
            .where(
                or_(Block.id.in_(ids), Block.parent_id.in_(ids), Block.id.in_(select(Block.parent_id).where(Block.id.in_(ids)).scalar_subquery())),
            )
        )
    )
    nodes: dict[int, Node] = {}
    for row in rows:
        owner_ok = row.page_id is None or page_read(viewer, SimpleNamespace(status=row.page_status, view_level=row.page_view_level))
        if not owner_ok or not block_view(viewer, row):
            continue
        try:
            model = t.validate_config(row.type, row.config)
        except (ValidationError, t.UnknownBlockType):
            continue
        nodes[row.id] = Node(row, model, collect_refs(model))
    for row in sorted(rows, key=lambda x: (x.sort_order, x.id)):
        if row.id in nodes and row.parent_id in nodes:
            nodes[row.parent_id].children.append(nodes[row.id])
    by_id = {row.id: row for row in rows}

    def parent_ok(i: int) -> bool:
        # 묶음 안의 블록을 id 로 바로 물어도 부모 묶음의 보이기(숨김·등급·대상)를 함께 본다 — 가지째(코드 검토 v9 B-1). 깊이 2 라 한 단
        parent = by_id[i].parent_id
        return parent is None or (parent in by_id and block_view(viewer, by_id[parent]))

    tops = [nodes[i] for i in ids if i in nodes and parent_ok(i)]
    every = [n for top in tops for n in _walk(top.children)] + tops
    refs = Refs()
    for n in every:
        refs.boards |= n.refs.boards
        refs.pages |= n.refs.pages
        refs.menus |= n.refs.menus
    menus = await _menus(db, refs.menus)  # ②
    for items in menus.values():
        refs.boards |= {i.board_id for i in items if i.link_kind == "board"}
        refs.pages |= {i.page_id for i in items if i.link_kind == "page"}
    targets = await _targets(db, refs.boards, refs.pages, viewer)  # ③
    post_targets = _recent_targets(every, "recent_posts")
    pinned = any(n.row.type == "recent_posts" and n.model.include_pinned for n in every)
    posts = await _recent_posts(db, post_targets, pinned, viewer)  # ④
    comments = await _recent_comments(db, _recent_targets(every, "recent_comments"), viewer)  # ⑤
    image_rows = await _images(db, {n.row.id for n in every})  # ⑥
    seo = await site_settings.load(db, "seo")  # ⑦
    assert isinstance(seo, site_settings.SeoSettings)
    images: dict[int, list[int]] = {}
    for row in image_rows:
        images.setdefault(row.block_id, []).append(row.id)
    lookup = r.Lookup(
        site_name=seo.site_name,
        page_paths=targets.pages,
        board_slugs={i: b.key for i, b in targets.boards.items() if b.listable},
        images=image_sources(image_rows),
        menus=menus,
        viewer_level=viewer.level,
    )

    def assemble() -> dict[int, r.View]:
        out: dict[int, r.View] = {}
        for n in tops:
            if (view := _out(n, lookup, targets, posts, comments, [], images)) is not None:
                out[n.row.id] = view
        return out

    return await run_in_thread("sanitize", assemble)
