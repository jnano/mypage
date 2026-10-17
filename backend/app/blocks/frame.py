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

from app.admin import settings as site_settings
from app.auth.viewer import GUEST
from app.blocks import resolve as r
from app.blocks import types as t
from app.blocks.menus import ITEM_COLUMNS
from app.blocks.limits import RECENT_COMMENT_POSTS
from app.blocks.tree import Refs, collect_refs, owner_blocks
from app.core.threads import run_in_thread
from app.editor.render import ImageSource
from app.files.attach import ROW_COLUMNS, image_sources, thumb_template
from app.models import Attachment, Board, Comment, Layout, LayoutBinding, MenuItem, Page, Post
from app.permissions import guest_listable_boards_clause, guest_readable_boards_clause, listable_posts_clause, readable_posts_clause

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
    return (await db.execute(select(Layout.id, Layout.version).where(Layout.id == chosen))).one_or_none()


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


async def _targets(db: AsyncSession, board_ids: set[int], page_ids: set[int]) -> Targets:
    """④ 참조 게시판·페이지 — 한 문장(UNION ALL). 게시판은 비회원 목록·열람 가능 여부와 최근 글 시각(게시판 바로가기)"""
    parts = []
    if board_ids:
        last = (
            select(Post.published_at)
            .where(Post.board_id == Board.id, listable_posts_clause(GUEST), Post.is_pinned.is_(False))
            .order_by(Post.published_at.desc(), Post.id.desc())
            .limit(1)
            .correlate(Board)
            .scalar_subquery()
        )
        parts.append(
            select(
                literal("board").label("kind"), Board.id, Board.slug.label("key"), Board.name,
                guest_listable_boards_clause().label("listable"), guest_readable_boards_clause().label("readable"),
                last.label("last_posted_at"),
            ).where(Board.id.in_(board_ids))
        )  # fmt: skip
    if page_ids:
        public = (Page.status == PUBLISHED) & (Page.view_level == 0)
        parts.append(
            select(
                literal("page").label("kind"), Page.id, Page.path.label("key"), Page.title.label("name"),
                public.label("listable"), public.label("readable"), literal(None).label("last_posted_at"),
            ).where(Page.id.in_(page_ids))
        )  # fmt: skip
    out = Targets()
    if not parts:
        return out
    for row in await db.execute(union_all(*parts) if len(parts) > 1 else parts[0]):
        if row.kind == "board":
            out.boards[row.id] = row
        elif row.listable:
            out.pages[row.id] = row.key
    return out


def _decide(nodes: Sequence[Node], menus: dict[int, list[Any]], targets: Targets) -> None:
    """비회원 기준으로 블록마다 공개·개인·회원이면 다시를 정한다(§6.1). 부모가 개인이면 가지째 개인"""
    listable = {i for i, b in targets.boards.items() if b.listable}
    readable = {i for i, b in targets.boards.items() if b.readable}
    for n in nodes:
        row = n.row
        if row.audience == "member" or row.min_level > 0:
            n.personal = True
        elif row.type in ("recent_posts", "recent_comments"):
            n.personal = not n.refs.boards <= readable  # 회원 전용 게시판의 글이 공개 캐시에 섞이지 않게(P1)
        elif row.type == "board_links":
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


async def _recent_posts(db: AsyncSession, targets: dict[int, int], pinned: bool) -> list[Any]:
    return list(await db.execute(recent_posts_statement(targets, pinned))) if targets else []


def recent_posts_statement(targets: dict[int, int], pinned: bool):
    """⑤ 최근 글 + 고정 글 — 게시판마다 LATERAL(공개 판정·만료 거르기는 LIMIT 앞, 검토 N-2). 한 문장.
    실행과 측정(scripts/explain_hotpaths.py)이 같은 문장을 쓴다"""
    t_ = _values(targets)

    def branch(is_pinned: bool):
        order = (Post.pin_order.asc().nulls_last(), Post.published_at.desc(), Post.id.desc()) if is_pinned else (Post.published_at.desc(), Post.id.desc())
        sub = (
            select(Post.id, Post.board_id, Post.title, Post.published_at, Post.is_pinned, Post.pin_order)
            .where(Post.board_id == t_.c.bid, readable_posts_clause(GUEST), _not_expired(), Post.is_pinned == (TRUE if is_pinned else FALSE))
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


async def _recent_comments(db: AsyncSession, targets: dict[int, int]) -> list[Any]:
    return list(await db.execute(recent_comments_statement(targets))) if targets else []


def recent_comments_statement(targets: dict[int, int], posts_per_board: int = RECENT_COMMENT_POSTS):
    """⑥ 최근 댓글 — 게시판마다 그 게시판의 최근 글(고정 글 포함) posts_per_board 개를 목록 인덱스로 고르고, 그 글들의
    최신 댓글을 글별 댓글 인덱스(ix_comments_post)로 모은다. 댓글이 드문 게시판도 훑는 양에 상한이 있다(M-1 측정 —
    전역 '최신 댓글' 인덱스를 거꾸로 훑으면 댓글 없는 게시판에서 수백 ms). 그래서 아주 오래된 글에 새로 달린 댓글은
    블록에 나오지 않는다(§5.2 M-1 결정). 실행과 측정(scripts/explain_hotpaths.py)이 같은 문장을 쓴다"""
    t_ = _values(targets)

    def board_posts(is_pinned: bool):
        order = (Post.pin_order.asc().nulls_last(),) if is_pinned else (Post.published_at.desc(), Post.id.desc())
        return (
            select(Post.id, Post.title)
            .where(Post.board_id == t_.c.bid, readable_posts_clause(GUEST), _not_expired(), Post.is_pinned == (TRUE if is_pinned else FALSE))
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


async def _images(db: AsyncSession, block_ids: set[int]) -> list[Any]:
    """⑦ 블록 그림"""
    if not block_ids:
        return []
    return list(await db.execute(select(*ROW_COLUMNS, Attachment.block_id).where(Attachment.block_id.in_(block_ids))))  # post-clause: exempt — 첨부 칸(글 아님)


def _excerpt(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= EXCERPT else text[: EXCERPT - 1] + "…"


def _dynamic_view(n: Node, targets: Targets, posts: Sequence[Any], comments: Sequence[Any]) -> r.View | None:
    m = n.model
    boards = [b for b in m.board_ids if b in targets.boards]
    slug = {b: targets.boards[b].key for b in boards}
    if isinstance(m, t.BoardLinks):
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


async def frame_bundle(db: AsyncSession, *, board_slug: str | None = None, route: str | None = None) -> dict[str, Any]:
    tags = ["layouts:bindings", "settings:seo"]
    if board_slug is not None:
        tags.append("boards:structure")  # 게시판의 틀(boards.layout_id) 바꾸기는 board.updated 가 이 태그를 즉시 만료한다
    owner = await _owner(db, board_slug, route)  # ①
    if owner is None:  # 틀이 하나도 없다 — 화면이 코드의 대체 틀을 쓴다(§3.6)
        return {"layout": None, "personal_block_ids": [], "cache": {"tags": tags}}
    tags.append(f"layout:{owner.id}")
    regions = _tree(await owner_blocks(db, "layout", owner.id))  # ②
    nodes = [n for top in regions.values() for n in _walk(top)]
    refs = Refs()
    for n in nodes:
        refs.boards |= n.refs.boards
        refs.pages |= n.refs.pages
        refs.menus |= n.refs.menus
    menus = await _menus(db, refs.menus)  # ③
    for rows in menus.values():
        refs.boards |= {i.board_id for i in rows if i.link_kind == "board"}
        refs.pages |= {i.page_id for i in rows if i.link_kind == "page"}
    targets = await _targets(db, refs.boards, refs.pages)  # ④
    _decide(nodes, menus, targets)
    post_targets = _recent_targets(nodes, "recent_posts")
    pinned = any(n.row.type == "recent_posts" and not n.personal and n.model.include_pinned for n in nodes)
    posts = await _recent_posts(db, post_targets, pinned)  # ⑤
    comments = await _recent_comments(db, _recent_targets(nodes, "recent_comments"))  # ⑥
    public_ids = {n.row.id for n in nodes if not n.personal}
    image_rows = await _images(db, public_ids)  # ⑦
    seo = await site_settings.load(db, "seo")  # ⑧
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
    )

    def assemble() -> tuple[dict[str, list[r.View]], list[int]]:
        personal: list[int] = []
        out: dict[str, list[r.View]] = {}
        for region in t.REGIONS:
            views = [v for n in regions.get(region, []) if (v := _out(n, lookup, targets, posts, comments, personal, images)) is not None]
            if views:
                out[region] = views
        return out, personal

    # 마크다운 변환·정화는 CPU 작업 — 이벤트 루프가 아니라 정화 스레드 한도 안에서(글 저장과 같은 한도, 코드 검토 v5 N-2)
    out_regions, personal = await run_in_thread("sanitize", assemble)
    tags += [f"menu:{m}" for m in sorted(refs.menus)]
    if refs.boards:
        tags.append("boards:structure")
    if post_targets:
        tags.append("recent:posts")
    if any(n.row.type == "recent_comments" and not n.personal for n in nodes):
        tags.append("recent:comments")
    return {
        "layout": {"id": owner.id, "version": owner.version, "regions": out_regions},
        "personal_block_ids": personal,
        "cache": {"tags": sorted(set(tags))},
    }

