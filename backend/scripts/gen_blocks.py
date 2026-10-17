"""블록 생성 파일 — 홈블록 설계도 §3.4·§4.4.2.

원본 app/blocks(types·modules·routes) → frontend/lib/blocks/blocks.gen.json(커밋한다). 프런트는 이 파일만 읽는다.
원본과 같은지는 tests/test_block_types.py 가 본다(생성에 Pydantic 이 필요해 백엔드 시험에서).

실행: cd backend && uv run python -m scripts.gen_blocks
"""

import json
import sys
from pathlib import Path

from app.blocks import types as t
from app.blocks.modules import MODULES
from app.blocks.resolve import NOT_YET, Lookup, resolve
from app.blocks.routes import PAGE_PATH_PATTERN
from app.editor.render import ImageSource

TARGET = Path(__file__).resolve().parents[2] / "frontend" / "lib" / "blocks" / "blocks.gen.json"

# 견본 해결용 조회 결과 — 그림은 '썸네일 전'(자리 표시)이라 없는 파일 주소를 만들지 않는다
EXAMPLE_LOOKUP = Lookup(
    site_name="예시 사이트",
    page_paths={1: "/about"},
    board_slugs={1: "notice"},
    images={1: ImageSource("", 1200, 600, thumbs_ready=False)},
)


def render() -> str:
    data = {
        "$generated": "backend/scripts/gen_blocks.py — 직접 고치지 않는다",
        "regions": list(t.REGIONS),
        "pagePathPattern": PAGE_PATH_PATTERN,
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
        },
    }
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(render(), encoding="utf-8")
    print(f"생성: {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
