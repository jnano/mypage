"""개발 시드의 홈블록 몫 — 홈블록 설계도 §3.6(개발 시드가 '기본 틀 만들기'와 같은 함수를 부른다)·§10(접근성 검사 화면).

운영자 함수(기본 틀 만들기·틀·페이지 저장)를 그대로 거친다 — 시드가 관리 화면과 같은 검증을 통과해야 화면도 같다.
- 기본 틀 + 주 메뉴(bootstrap)
- 게시판 화면 틀: 기본 틀과 같은 머리·바닥 + 옆 메뉴(접근성 '옆 메뉴가 있는 게시판 목록') — 화면 종류 board 에 대응
- 첫 화면 페이지 `/`: 최근 글 둘(공지·자유게시판)
- 견본 페이지 `/sample`: 그림 없이 그릴 수 있는 콘텐츠·동적·구조·모듈 블록(그림·배너는 실제 파일이 필요해 /dev/blocks 견본이 맡는다)
예시 문구는 중립어(본 §2.4).
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.viewer import Viewer
from app.blocks import layouts, pages, tree
from app.blocks.bootstrap import bootstrap

SAMPLE_PATH = "/sample"


def _block(type_: str, config: dict[str, Any] | None = None, **kw: Any) -> tree.BlockIn:
    return tree.BlockIn(type=type_, config=config or {}, **kw)


async def _page(db: AsyncSession, admin: Viewer, path: str, title: str, blocks: list[tree.BlockIn], description: str | None = None) -> int:
    created = await pages.create_page(db, admin, pages.PageCreate(path=path, title=title))
    body = pages.PageSave(path=path, title=title, description=description, blocks=blocks)
    await pages.save_page(db, admin, created["id"], body, created["version"])
    await pages.set_status(db, admin, created["id"], True)
    return created["id"]


async def seed_homeblock(db: AsyncSession, admin: Viewer, boards: dict[str, int]) -> dict[str, int]:
    made = await bootstrap(db, admin)
    menu_id, default_id = made["menu_id"], made["layout_id"]

    board_layout = await layouts.create_layout(db, admin, layouts.LayoutCreate(name="게시판 화면 틀"))
    default = await layouts.layout_detail(db, default_id)
    same = lambda region: [tree.BlockIn.model_validate(b) for b in default["regions"][region]]  # noqa: E731 — 기본 틀과 같은 머리·바닥
    strip = lambda items: [b.model_copy(update={"id": None}) for b in items]  # noqa: E731 — 새 틀의 블록(다른 주인의 id 는 422)
    regions = {
        "header": strip(same("header")),
        "aside": [_block("sub_menu", {"menu_id": menu_id, "label": "게시판 메뉴"})],
        "footer": strip(same("footer")),
    }
    await layouts.save_layout(db, admin, board_layout["id"], layouts.LayoutSave(name="게시판 화면 틀", regions=regions), board_layout["version"])
    await layouts.save_bindings(db, admin, layouts.BindingsSave(bindings={"board": board_layout["id"]}))

    home = await _page(
        db,
        admin,
        "/",
        "처음",
        [
            _block("recent_posts", {"title": "공지", "board_ids": [boards["notice"]], "count": 5}),
            _block("recent_posts", {"title": "자유게시판 새 글", "board_ids": [boards["free"]], "count": 5}),
        ],
        "사이트의 새 소식입니다.",
    )
    sample = await _page(
        db,
        admin,
        SAMPLE_PATH,
        "블록 견본",
        [
            _block("heading", {"text": "안내", "level": 2}),
            _block("text", {"source": "이 페이지는 **블록 견본**입니다.\n\n- 목록 항목 하나\n- 목록 항목 둘"}),
            _block("buttons", {"items": [
                {"label": "공지 보기", "link": {"kind": "board", "board_id": boards["notice"]}},
                {"label": "처음으로", "link": {"kind": "page", "page_id": home}},
            ]}),  # fmt: skip
            _block("link_list", {"title": "바로가기", "items": [
                {"label": "자유게시판", "link": {"kind": "board", "board_id": boards["free"]}},
                {"label": "예시 사이트", "link": {"kind": "url", "url": "https://example.org", "new_window": True}},
            ]}),  # fmt: skip
            _block("video", {"url": "https://youtu.be/aaaaaaaaaaa", "title": "안내 영상"}),
            _block("details", {"items": [{"question": "회의는 언제인가요?", "answer": "매주 **화요일** 오후입니다."}]}),
            _block("divider"),
            _block("group", {"title": "새 소식", "landmark": True}, children=[
                _block("recent_posts", {"title": "최근 글", "board_ids": [boards["free"]], "view": "photo", "count": 3}),
                _block("recent_comments", {"title": "최근 댓글", "board_ids": [boards["free"]]}),
            ]),  # fmt: skip
            _block("columns", {"count": 2}, children=[
                _block("board_links", {"title": "게시판", "board_ids": [boards["notice"], boards["free"], boards["members"]]}, column_index=0),
                _block("heading", {"text": "회원 안내", "level": 3}, column_index=1, audience="member"),
            ]),  # fmt: skip
            _block("module", {"module": "board", "params": {"board_id": boards["free"], "count": 5}}),
        ],
        "블록 종류를 한 화면에 모은 견본입니다.",
    )
    return {"default_layout": default_id, "board_layout": board_layout["id"], "menu": menu_id, "home": home, "sample": sample}
