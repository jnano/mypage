"""홈블록 측정 시드 — 홈블록 설계도 §12. 측정 전용 DB(이름이 _bench 로 끝나야 함)에만 넣는다.

기존 측정 DB(scripts.seed_posts — 글 10만·댓글 27만) 위에 **최대 구성**을 운영자 저장 함수 그대로 만든다(관리 화면과 같은 검증):
- 게시판 3개 더(글 30개씩) — 게시판 10개 × 최근 글 20개를 채운다
- 메뉴 '측정 메뉴' 항목 200(3단)
- 기본 틀 — 블록 60(상한), 데이터를 부르는 블록 10(상한): 최근 글 5(게시판 10·20개, 사진 보기·고정 글 포함), 최근 댓글 4(그중 하나는
  댓글이 드문 게시판만 — §12 '최악'), 게시판 바로가기 1. 나머지는 마크다운 글·링크 목록 30·질문 30·단추·묶음·칸 나누기
- 페이지 /bench-max — 블록 60(동적 10: 모듈 1 포함) → 주소 묶음 = 틀 60 + 페이지 60
- 페이지 /bench-member — 회원 블록 30(회원 대상·등급·회원 전용 게시판) → `page-state?blocks=` 30개 측정용
- **보통 구성**(`--typical`, 비교용): 메뉴 15항목, 틀 '보통 틀'(머리 넷·옆 메뉴·최근 글 하나·바닥) — 게시판 qna 가 이 틀을 쓴다,
  페이지 /bench-typical(블록 12: 최근 글 둘·글·단추·링크 목록·묶음)
이미 만든 것이 있으면 건너뛴다.

실행: cd backend && DATABASE_URL=postgresql+asyncpg://taehunkang@localhost:5432/mypage_hb_bench uv run python -m scripts.seed_blocks [--typical]
순서(보고서에 적는다): seed_posts → seed_blocks → VACUUM (ANALYZE) → 측정.
"""

import asyncio
import random
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import make_url

from app.auth.viewer import Viewer
from app.blocks import layouts, menus, pages, tree
from app.blocks.limits import MAX_BLOCKS_PER_OWNER, MAX_DYNAMIC_BLOCKS, MAX_MENU_ITEMS
from app.boards.settings import UploadPolicy, default_display
from app.core.config import settings
from app.db.session import SessionLocal, engine
from app.editor.content import build_content
from app.models import Board, Member, Menu
from app.posts.schemas import PostCreate
from app.posts.service import insert_post
from app.search.index import content_fields, title_fields

SEED = 20261017
MENU_NAME = "측정 메뉴"
EXTRA_BOARDS = [("bench-h", "측정 게시판 하나"), ("bench-i", "측정 게시판 둘"), ("bench-j", "측정 게시판 셋")]
WORDS = ["회의", "안내", "모집", "일정", "자료", "공지", "행사", "준비", "정리", "참여", "결과", "보고"]


def _assert_bench_db() -> None:
    name = make_url(settings.database_url).database or ""
    if not name.endswith("_bench"):
        raise SystemExit(f"측정 전용 DB(이름이 _bench 로 끝남)에서만 실행합니다: {name}")


def _b(type_: str, config: dict[str, Any] | None = None, **kw: Any) -> tree.BlockIn:
    return tree.BlockIn(type=type_, config=config or {}, **kw)


def _markdown(rng: random.Random, chars: int) -> str:
    out: list[str] = []
    while sum(map(len, out)) < chars:
        out.append(f"## {rng.choice(WORDS)} {rng.choice(WORDS)}\n\n" + " ".join(rng.choice(WORDS) for _ in range(40)) + ".\n\n- **" + rng.choice(WORDS) + "** 항목\n- 다음 항목\n")
    return "\n".join(out)[:chars]


def _menu_items(boards: list[int], page_ids: list[int]) -> list[menus.MenuItemIn]:
    """3단 200개 — 맨 위 10(묶음 제목) × 3 × 5 + 맨 위 링크 10"""
    links = [{"kind": "board", "board_id": b} for b in boards] + [{"kind": "page", "page_id": p} for p in page_ids] + [{"kind": "url", "url": f"/boards/free?page={i}"} for i in range(1, 20)]
    k = 0

    def link() -> dict[str, Any]:
        nonlocal k
        k += 1
        return links[k % len(links)]

    items = []
    for i in range(10):
        children = [
            menus.MenuItemIn(label=f"항목 {i + 1}-{j + 1}", link=link(), children=[menus.MenuItemIn(label=f"항목 {i + 1}-{j + 1}-{g + 1}", link=link(), min_level=g % 3) for g in range(5)])
            for j in range(3)
        ]
        items.append(menus.MenuItemIn(label=f"묶음 {i + 1}", link=None, children=children))
    items += [menus.MenuItemIn(label=f"바로가기 {i + 1}", link=link()) for i in range(10)]
    return items


def _fill(blocks: list[tree.BlockIn], rng: random.Random, target: int, board: int, page: int, owner: str) -> list[tree.BlockIn]:
    """정적 콘텐츠로 블록 수를 target 까지(묶음·칸 나누기의 자식도 센다). 놓을 수 있는 곳(types.SPECS places)을 따른다 — 질문은 페이지만"""
    count = lambda xs: sum(1 + len(x.children) for x in xs)  # noqa: E731
    i = 0
    while count(blocks) < target:
        kind = i % 6
        if kind == 0:
            blocks.append(_b("text", {"source": _markdown(rng, 3_000)}))
        elif kind == 1:
            blocks.append(_b("link_list", {"title": f"바로가기 {i}", "items": [{"label": f"링크 {n}", "link": {"kind": "board", "board_id": board} if n % 2 else {"kind": "url", "url": f"/boards/free?page={n}"}} for n in range(30)]}))
        elif kind == 2 and owner == "page":
            blocks.append(_b("details", {"items": [{"question": f"질문 {n}은 무엇인가요?", "answer": _markdown(rng, 300)} for n in range(30)]}))
        elif kind == 3:
            blocks.append(_b("buttons", {"items": [{"label": f"단추 {n}", "link": {"kind": "page", "page_id": page} if n % 2 else {"kind": "board", "board_id": board}} for n in range(6)]}))
        elif kind == 4 and target - count(blocks) >= 3:
            # 랜드마크 이름은 같은 화면(틀 + 페이지)에서 달라야 한다(§10) — 주인마다 앞말을 다르게
            blocks.append(_b("group", {"title": f"{'틀' if owner == 'layout' else '페이지'} 묶음 {i}", "landmark": True}, children=[_b("heading", {"text": f"안내 {i}", "level": 3}), _b("text", {"source": _markdown(rng, 500)})]))
        else:
            blocks.append(_b("heading", {"text": f"제목 {i}", "level": 2}))
        i += 1
    return blocks


async def main() -> None:
    _assert_bench_db()
    rng = random.Random(SEED)
    async with SessionLocal() as db, db.begin():
        if (await db.execute(select(Menu.id).where(Menu.name == MENU_NAME))).first():
            print("이미 측정 메뉴가 있습니다 — 건너뜁니다")
            return
        admin_row = (await db.execute(select(Member).where(Member.is_admin.is_(True)).order_by(Member.id).limit(1))).scalar_one()
        admin = Viewer(member_id=admin_row.id, level=9, is_admin=True)
        author = Viewer(member_id=admin_row.id, level=admin_row.level, is_admin=True)

        upload = UploadPolicy().model_dump()
        for i, (slug, name) in enumerate(EXTRA_BOARDS):
            board = Board(slug=slug, name=name, kind="default", sort_order=20 + i, editor="markdown", upload_policy=upload, display=default_display("default").model_dump())
            db.add(board)
            await db.flush()
            for n in range(30):
                body = PostCreate(title=f"{rng.choice(WORDS)} {rng.choice(WORDS)} {n}", content=_markdown(rng, 400))
                content = await build_content(board.editor, body.content)
                await insert_post(db, author, board, body, content, title_fields(body.title) | content_fields(content.text))
        boards = {b.slug: b.id for b in (await db.execute(select(Board).order_by(Board.id))).scalars()}
        ten = list(boards.values())[:10]
        sparse = [boards[s] for s in ("qna", "consult", "small-a", "small-b", "notice", "bench-h", "bench-i", "bench-j") if s in boards]  # 댓글이 없거나 드문 게시판(§12 최악)

        # 페이지 먼저(메뉴·단추가 가리킨다) — 블록은 아래에서 채운다
        page_max = await pages.create_page(db, admin, pages.PageCreate(path="/bench-max", title="측정 최대 페이지"))
        page_member = await pages.create_page(db, admin, pages.PageCreate(path="/bench-member", title="측정 회원 블록 페이지"))

        menu = await menus.create_menu(db, admin, menus.MenuCreate(name=MENU_NAME))
        items = _menu_items(ten, [page_max["id"], page_member["id"]])
        flat_count = len(menus._flatten(items))
        assert flat_count == MAX_MENU_ITEMS, flat_count
        await menus.save_menu(db, admin, menu["id"], menus.MenuSave(name=MENU_NAME, items=items), menu["version"])

        # 기본 틀 — 블록 60, 동적 10
        dynamic = [
            _b("recent_posts", {"title": "최근 글", "board_ids": ten, "count": 20, "include_pinned": True}),
            _b("recent_posts", {"title": "사진", "board_ids": ten, "count": 20, "view": "photo"}),
            _b("recent_posts", {"title": "최근 글 둘", "board_ids": ten[:5], "count": 20}),
            _b("recent_posts", {"title": "최근 글 셋", "board_ids": ten[5:], "count": 20}),
            _b("recent_posts", {"title": "최근 글 넷", "board_ids": ten[::2], "count": 20}),
            _b("recent_comments", {"title": "최근 댓글", "board_ids": ten, "count": 20}),
            _b("recent_comments", {"title": "드문 게시판 댓글", "board_ids": sparse[:10], "count": 20}),
            _b("recent_comments", {"title": "자유게시판 댓글", "board_ids": [boards["free"]], "count": 20}),
            _b("recent_comments", {"title": "최근 댓글 둘", "board_ids": ten[1:], "count": 20}),
        ]
        regions = {
            "header": [_b("site_brand", {"show_name": True}), _b("menu", {"menu_id": menu["id"], "label": "주 메뉴", "depth": 2}), _b("search_box"), _b("account")],
            "nav": [_b("breadcrumb", {"menu_id": menu["id"], "label": "현재 위치"})],
            "aside": [_b("sub_menu", {"menu_id": menu["id"], "label": "옆 메뉴"}), _b("board_links", {"title": "게시판", "board_ids": ten})],
            "top": dynamic,
            "footer": [_b("footer_info", {"lines": [{"label": f"항목 {n}", "value": f"내용 {n}"} for n in range(10)], "copyright": "© 측정 사이트"})],
        }
        used = sum(1 + len(b.children) for r in regions.values() for b in r)
        regions["bottom"] = _fill([], rng, MAX_BLOCKS_PER_OWNER - used, boards["free"], page_max["id"], "layout")
        layout = await layouts.create_layout(db, admin, layouts.LayoutCreate(name="측정 최대 틀"))
        await layouts.save_layout(db, admin, layout["id"], layouts.LayoutSave(name="측정 최대 틀", regions=regions), layout["version"])
        await layouts.set_default(db, admin, layout["id"])

        # 페이지 /bench-max — 블록 60, 동적 10(모듈 1)
        page_dynamic = [
            _b("module", {"module": "board", "params": {"board_id": boards["free"], "count": 30}}),
            *[_b("recent_posts", {"title": f"페이지 최근 글 {n}", "board_ids": ten, "count": 20}) for n in range(5)],
            *[_b("recent_comments", {"title": f"페이지 최근 댓글 {n}", "board_ids": ten, "count": 20}) for n in range(3)],
            _b("board_links", {"title": "페이지 게시판", "board_ids": ten}),
        ]
        assert len(page_dynamic) == MAX_DYNAMIC_BLOCKS
        page_blocks = _fill([*page_dynamic, _b("columns", {"count": 3}, children=[_b("heading", {"text": f"칸 {c}", "level": 3}, column_index=c) for c in range(3)])], rng, MAX_BLOCKS_PER_OWNER, boards["free"], page_max["id"], "page")
        await pages.save_page(db, admin, page_max["id"], pages.PageSave(path="/bench-max", title="측정 최대 페이지", blocks=page_blocks), page_max["version"])
        await pages.set_status(db, admin, page_max["id"], True)

        # 페이지 /bench-member — 회원 블록 30(동적 10 — 회원 전용 게시판 포함)
        member_blocks = [
            *[_b("recent_posts", {"title": f"회원 최근 글 {n}", "board_ids": ten, "count": 20}) for n in range(5)],
            *[_b("recent_comments", {"title": f"회원 최근 댓글 {n}", "board_ids": ten, "count": 20}) for n in range(4)],
            _b("board_links", {"title": "회원 게시판", "board_ids": ten}),
            *[_b("text", {"source": _markdown(rng, 1_000)}, audience="member") for _ in range(10)],
            *[_b("heading", {"text": f"등급 안내 {n}", "level": 2}, min_level=1 + n % 3) for n in range(10)],
        ]
        await pages.save_page(db, admin, page_member["id"], pages.PageSave(path="/bench-member", title="측정 회원 블록 페이지", blocks=member_blocks), page_member["version"])
        await pages.set_status(db, admin, page_member["id"], True)
        out = {"layout": layout["id"], "menu": menu["id"], "page_max": page_max["id"], "page_member": page_member["id"], "boards": ten}
    print("측정 시드 완료:", out)
    await engine.dispose()


TYPICAL_MENU = "보통 메뉴"


async def typical() -> None:
    """보통 구성 — 같은 측정 DB 에서 최대 구성과 나란히 잰다(설계 상한이 아니라 흔한 사이트 크기)"""
    _assert_bench_db()
    rng = random.Random(SEED + 1)
    async with SessionLocal() as db, db.begin():
        if (await db.execute(select(Menu.id).where(Menu.name == TYPICAL_MENU))).first():
            print("이미 보통 구성이 있습니다 — 건너뜁니다")
            return
        admin_row = (await db.execute(select(Member).where(Member.is_admin.is_(True)).order_by(Member.id).limit(1))).scalar_one()
        admin = Viewer(member_id=admin_row.id, level=9, is_admin=True)
        boards = {b.slug: b for b in (await db.execute(select(Board).order_by(Board.id))).scalars()}
        page = await pages.create_page(db, admin, pages.PageCreate(path="/bench-typical", title="측정 보통 페이지"))
        menu = await menus.create_menu(db, admin, menus.MenuCreate(name=TYPICAL_MENU))
        items = [menus.MenuItemIn(label="처음", link={"kind": "url", "url": "/"})]
        items += [menus.MenuItemIn(label=b.name, link={"kind": "board", "board_id": b.id}) for b in list(boards.values())[:5]]
        items += [menus.MenuItemIn(label="안내", link=None, children=[menus.MenuItemIn(label=f"안내 {n}", link={"kind": "page", "page_id": page["id"]}) for n in range(7)])]
        items += [menus.MenuItemIn(label="검색", link={"kind": "url", "url": "/search"})]
        await menus.save_menu(db, admin, menu["id"], menus.MenuSave(name=TYPICAL_MENU, items=items), menu["version"])
        regions = {
            "header": [_b("site_brand", {"show_name": True}), _b("menu", {"menu_id": menu["id"], "label": "사이트", "depth": 2}), _b("search_box"), _b("account")],
            "aside": [_b("sub_menu", {"menu_id": menu["id"], "label": "게시판 메뉴"}), _b("recent_posts", {"title": "새 글", "board_ids": [boards["free"].id], "count": 5})],
            "footer": [_b("footer_info", {"copyright": "© 측정 사이트"})],
        }
        layout = await layouts.create_layout(db, admin, layouts.LayoutCreate(name="보통 틀"))
        await layouts.save_layout(db, admin, layout["id"], layouts.LayoutSave(name="보통 틀", regions=regions), layout["version"])
        qna = boards["qna"]
        qna.layout_id = layout["id"]  # 게시판 화면 비교 — qna 만 보통 틀
        blocks = [
            _b("recent_posts", {"title": "공지", "board_ids": [boards["notice"].id], "count": 5}),
            _b("recent_posts", {"title": "자유게시판", "board_ids": [boards["free"].id], "count": 5}),
            _b("text", {"source": _markdown(rng, 1_000)}),
            _b("buttons", {"items": [{"label": "공지", "link": {"kind": "board", "board_id": boards["notice"].id}}, {"label": "질문", "link": {"kind": "board", "board_id": qna.id}}]}),
            _b("link_list", {"title": "바로가기", "items": [{"label": b.name, "link": {"kind": "board", "board_id": b.id}} for b in list(boards.values())[:5]]}),
            _b("group", {"title": "소식", "landmark": True}, children=[_b("heading", {"text": "이번 주", "level": 3}), _b("text", {"source": _markdown(rng, 500)})]),
            _b("heading", {"text": "알림", "level": 2}),
            _b("text", {"source": _markdown(rng, 600)}),
            _b("divider"),
        ]
        await pages.save_page(db, admin, page["id"], pages.PageSave(path="/bench-typical", title="측정 보통 페이지", layout_id=layout["id"], blocks=blocks), page["version"])
        await pages.set_status(db, admin, page["id"], True)
        # 첫 화면 '/' 도 보통 구성(k6 home 이 늘 '/' 를 함께 본다 — 최대 틀의 기본 틀로 그려지면 보통 구성 측정에 무거운 화면이 섞인다)
        home = await pages.create_page(db, admin, pages.PageCreate(path="/", title="처음"))
        await pages.save_page(db, admin, home["id"], pages.PageSave(path="/", title="처음", layout_id=layout["id"], blocks=blocks[:2] + blocks[3:5]), home["version"])
        await pages.set_status(db, admin, home["id"], True)
    print("보통 구성 완료:", {"layout": layout["id"], "menu": menu["id"], "page": page["id"]})
    await engine.dispose()


if __name__ == "__main__":
    import sys

    asyncio.run(typical() if "--typical" in sys.argv else main())
