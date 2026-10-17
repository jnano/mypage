"""관리 화면의 블록 설정 폼 형식 — 홈블록 설계도 §7(GET /api/admin/block-types)·§8.

형식은 types.py 의 Pydantic 모델이 만든 JSON Schema 그대로다(칸 명세를 프런트에 따로 쓰지 않는다 — 원칙 2). 여기서는
사람이 읽을 이름(title)·도움말(description)·입력 부품(x-widget)·고르기 이름(x-enum-labels)만 덧붙인다. 칸마다 이름이
있어야 한다 — 없으면 만들 때 예외(새 칸을 더하고 이름을 빠뜨리면 시험이 실패한다).
"""

from typing import Any

from pydantic import BaseModel

from app.blocks import types as t
from app.blocks.modules import MODULES

# 입력 부품 — 프런트 components/admin/blocks/fields 가 이 이름으로 부품을 고른다(형식만으로 알 수 없는 것만)
Widget = str
IMAGE, MARKDOWN, TEXTAREA, MENU, PAGE, BOARD, BOARDS, MODULE, MODULE_PARAMS = (
    "image", "markdown", "textarea", "menu", "page", "board", "boards", "module", "module-params",
)  # fmt: skip

# 칸 이름 → (이름, 부품). 같은 이름이 모델마다 뜻이 다르면 아래 _BY_MODEL 이 먼저
_FIELDS: dict[str, tuple[str, Widget | None]] = {
    "logo_attachment_id": ("로고 그림", IMAGE),
    "logo_alt": ("로고 설명(대체 텍스트)", None),
    "show_name": ("사이트 이름 보이기", None),
    "menu_id": ("메뉴", MENU),
    "depth": ("펼칠 단계", None),
    "show_root_title": ("맨 위 항목 제목 보이기", None),
    "placeholder": ("입력 칸 안내 글자", None),
    "lines": ("줄", None),
    "value": ("내용", None),
    "copyright": ("저작권 문구", None),
    "text": ("제목 글자", None),
    "level": ("제목 단계", None),
    "source": ("본문(마크다운)", MARKDOWN),
    "attachment_id": ("그림", IMAGE),
    "alt": ("그림 설명(대체 텍스트)", None),
    "decorative": ("꾸밈용 그림(설명 없음)", None),
    "link": ("링크", None),
    "title": ("제목", None),
    "description": ("설명", TEXTAREA),
    "buttons": ("단추", None),
    "items": ("항목", None),
    "url": ("주소", None),
    "question": ("질문", None),
    "answer": ("답(마크다운, 그림 없음)", MARKDOWN),
    "board_ids": ("게시판", BOARDS),
    "count": ("개수", None),
    "view": ("보기", None),
    "include_pinned": ("고정 글을 앞에 넣기", None),
    "landmark": ("랜드마크로 내보내기(제목이 이름이 됨)", None),
    "module": ("모듈", MODULE),
    "params": ("모듈 설정", MODULE_PARAMS),
    "kind": ("링크 종류", None),
    "page_id": ("페이지", PAGE),
    "board_id": ("게시판", BOARD),
    "new_window": ("새 창으로 열기", None),
    "min_level": ("최소 회원 등급(표시 조건, 0 = 모두)", None),
    "is_active": ("보이기", None),
}
_BY_MODEL: dict[tuple[str, str], tuple[str, Widget | None]] = {
    ("Menu", "label"): ("탐색 이름(화면 읽기 프로그램이 읽음)", None),
    ("SubMenu", "label"): ("탐색 이름(화면 읽기 프로그램이 읽음)", None),
    ("Breadcrumb", "label"): ("탐색 이름(화면 읽기 프로그램이 읽음)", None),
    ("Button", "label"): ("단추 글자", None),
    ("LinkItem", "label"): ("항목 이름", None),
    ("FooterLine", "label"): ("항목 이름", None),
    ("Buttons", "items"): ("단추", None),
    ("LinkList", "items"): ("링크", None),
    ("Details", "items"): ("질문과 답", None),
    ("Video", "url"): ("동영상 주소(허용된 곳만)", None),
    ("MenuItemFields", "label"): ("항목 이름", None),
    ("MenuItemFields", "link"): ("링크(없으면 아래 항목을 펼치는 제목)", None),
}
# 고르기 값 → 보이는 이름(숫자 고르기는 값 그대로)
_ENUM_LABELS: dict[str, dict[str, str]] = {
    "kind": {"page": "페이지", "board": "게시판", "url": "주소"},
    "view": {"list": "목록", "photo": "사진", "card": "카드", "line": "한 줄"},
}
# 종류의 도움말 — 설정만 보고 알기 어려운 뜻(§4.4.1)
HELP: dict[str, str] = {
    "recent_comments": "고른 게시판마다 최근 글 100개에 달린 댓글 중 새것을 보여 줍니다. 아주 오래된 글에 새로 달린 댓글은 나오지 않습니다.",
    "recent_posts": "회원 전용 게시판을 고르면 이 블록은 볼 수 있는 회원에게만 보입니다.",
    "board_links": "목록을 볼 수 없는 사람에게는 그 게시판이 빠집니다.",
    "module": "페이지마다 하나. 게시판 모듈은 그 게시판의 첫 쪽 글과 '더 보기'를 보여 줍니다.",
    "group": "묶음 안에 다른 블록을 넣습니다(묶음 안에 묶음은 넣을 수 없습니다).",
    "columns": "칸마다 블록을 넣습니다. 좁은 화면에서는 위아래로 쌓입니다.",
}


def _annotate(node: Any, model_name: str | None = None) -> None:
    """JSON Schema 를 돌며 객체의 칸마다 이름·부품을 단다. 객체의 title 은 Pydantic 이 붙인 모델 이름"""
    if isinstance(node, dict):
        props = node.get("properties")
        if isinstance(props, dict):
            node.pop("description", None)  # 모델 docstring — 개발자 주석이라 운영자 화면에 내지 않는다(도움말은 HELP)
            owner = node.get("title", model_name)
            for name, prop in props.items():
                meta = _BY_MODEL.get((owner, name)) or _FIELDS.get(name)
                if meta is None:
                    raise KeyError(f"블록 설정 칸 이름이 없습니다: {owner}.{name} — app/blocks/schema.py 에 더합니다")
                prop["title"], widget = meta
                if widget is not None:
                    prop["x-widget"] = widget
                if name in _ENUM_LABELS:
                    prop["x-enum-labels"] = _ENUM_LABELS[name]
        for v in node.values():
            _annotate(v, model_name)
    elif isinstance(node, list):
        for v in node:
            _annotate(v, model_name)


def form_schema(model: type[BaseModel]) -> dict[str, Any]:
    schema = model.model_json_schema()
    _annotate(schema)
    return schema


def block_types() -> dict[str, Any]:
    """종류(이름·갈래·놓을 곳·쓸 수 있음·설정 형식·도움말)와 모듈(이름·설정 형식). 대기 종류는 형식 없이 이름만"""
    out = []
    for key, spec in t.SPECS.items():
        if key == "outlet":  # 렌더러가 놓는 자리 — 운영자가 더하지 않는다(§3.1)
            continue
        item: dict[str, Any] = {"type": key, "label": spec.label, "group": spec.group, "places": list(spec.places), "available": spec.available}
        if spec.available and spec.model is not None:
            item["schema"] = form_schema(spec.model)
            item["example"] = spec.example
        if key in HELP:
            item["help"] = HELP[key]
        out.append(item)
    modules = {
        k: {"label": m.label, "available": m.available, "schema": form_schema(m.params_model)} for k, m in MODULES.items()
    }
    # 메뉴 항목 폼(§8 메뉴 편집) — 같은 링크 형식·같은 이름표 규칙을 블록과 함께 쓴다. menus 를 여기서 부르면 순환이라 늦게
    from app.blocks.menus import MenuItemFields

    return {
        "types": out,
        "modules": modules,
        "menu_item": form_schema(MenuItemFields),
        "regions": list(t.REGIONS),
        "audiences": list(t.AUDIENCES),
    }
