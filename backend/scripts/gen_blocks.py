"""블록 생성 파일 — 홈블록 설계도 §3.4·§4.4.2.

원본 app/blocks(types·modules·routes) → frontend/lib/blocks/blocks.gen.json(커밋한다). 프런트는 이 파일만 읽는다.
원본과 같은지는 tests/test_block_types.py 가 본다(생성에 Pydantic 이 필요해 백엔드 시험에서).

실행: cd backend && uv run python -m scripts.gen_blocks
"""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from app.blocks import frame
from app.blocks import types as t
from app.blocks.modules import MODULES
from app.blocks.resolve import NOT_YET, Lookup, resolve
from app.blocks.routes import PAGE_PATH_PATTERN, PAGE_PATH_SAMPLES
from app.blocks.tree import collect_refs
from app.blocks.menus import ITEM_COLUMNS
from app.editor.render import ImageSource


def _item(id: int, parent: int | None, order: int, label: str, kind: str = "url", url: str | None = None, page: int | None = None):
    row = dict.fromkeys(c.key for c in ITEM_COLUMNS)
    row.update(id=id, parent_id=parent, sort_order=order, label=label, link_kind=kind, url=url, page_id=page,
               new_window=False, min_level=0, is_active=True)  # fmt: skip
    return SimpleNamespace(**row)


# 견본 메뉴 — 2단 묶음(링크 없는 제목)·페이지·게시판 주소·바깥 주소·견본 화면 자신
EXAMPLE_MENU = [
    _item(1, None, 0, "소개", "none"),
    _item(2, 1, 0, "인사말", "page", page=1),
    _item(3, 1, 1, "찾아오는 길", url="/about/map"),
    _item(8, 1, 2, "블록 견본", url="/dev/blocks"),  # 견본 화면 자신 — 지금 항목·경로 표시·옆 메뉴가 그려진다
    _item(4, None, 1, "공지", url="/boards/notice"),
    _item(5, None, 2, "자유게시판", url="/boards/free"),
    _item(6, 5, 0, "글쓰기", url="/boards/free/write"),
    _item(7, None, 3, "예시 사이트", url="https://example.org"),
]

TARGET = Path(__file__).resolve().parents[2] / "frontend" / "lib" / "blocks" / "blocks.gen.json"

# 견본 해결용 조회 결과 — 그림은 '썸네일 전'(자리 표시)이라 없는 파일 주소를 만들지 않는다
EXAMPLE_LOOKUP = Lookup(
    site_name="예시 사이트",
    page_paths={1: "/about"},
    board_slugs={1: "notice"},
    images={1: ImageSource("", 1200, 600, thumbs_ready=False)},
    menus={1: EXAMPLE_MENU},
)


AT = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)  # 견본 시각 — 생성 파일이 실행 때마다 바뀌지 않게 고정


def _dynamic_examples() -> dict[str, object]:
    """동적 블록 견본 — 틀 묶음이 쓰는 함수(frame._dynamic_view)에 고정 행을 넣어 만든다(손으로 쓰지 않는다)"""
    board = SimpleNamespace(key="notice", name="공지", listable=True, readable=True, last_posted_at=AT)
    post = dict(board_id=1, published_at=AT, pin_order=None, cover_id=None, storage_key=None, visibility=None,
                width=None, height=None, thumbs_ready=False)  # fmt: skip
    posts = [
        SimpleNamespace(**post | {"id": 10, "title": "이번 주 회의 안내", "is_pinned": True, "pin_order": 1}),
        SimpleNamespace(**post | {"id": 11, "title": "모집 공고", "is_pinned": False}),
    ]
    comments = [SimpleNamespace(id=20, post_id=11, board_id=1, content="참여하겠습니다.", created_at=AT,
                                author_name_snapshot="회원", post_title="모집 공고")]  # fmt: skip
    out = {}
    for k in frame.DYNAMIC:
        model = t.validate_config(k, t.SPECS[k].example)
        node = frame.Node(row=SimpleNamespace(type=k), model=model, refs=collect_refs(model))
        out[k] = frame._dynamic_view(node, frame.Targets(boards={1: board}), posts, comments)
    return out


def render() -> str:
    data = {
        "$generated": "backend/scripts/gen_blocks.py — 직접 고치지 않는다",
        "regions": list(t.REGIONS),
        "pagePathPattern": PAGE_PATH_PATTERN,
        "pagePathSamples": [[path, ok] for path, ok in PAGE_PATH_SAMPLES],
        "types": [
            {"type": k, "label": s.label, "group": s.group, "places": list(s.places), "available": s.available}
            for k, s in t.SPECS.items()
        ],
        "modules": [{"key": m.key, "label": m.label, "available": m.available} for m in MODULES.values()],
        # 지금 그릴 수 있는 종류의 견본(개발 견본 화면 /dev/blocks)
        "examples": {
            k: resolve(k, s.example, EXAMPLE_LOOKUP, attachment_ids=(1,))
            for k, s in t.SPECS.items()
            if s.available and k not in NOT_YET
        }
        | _dynamic_examples(),
    }
    return json.dumps(data, ensure_ascii=False, indent=2, default=lambda v: v.isoformat()) + "\n"


def main() -> int:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(render(), encoding="utf-8")
    print(f"생성: {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
