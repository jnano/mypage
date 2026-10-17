"""블록 종류 등록부·설정 형식·해결·생성 파일 — 홈블록 설계도 §2.2·§4.4·§13('블록 설정 형식'·'레지스트리 계약')."""

from typing import Any

import pytest
from pydantic import ValidationError

from app.blocks import types as t
from app.blocks.modules import MODULES
from app.blocks.resolve import NOT_YET, Lookup, link, resolve
from app.editor.render import ImageSource
from scripts.gen_blocks import TARGET, render

URL = {"kind": "url", "url": "/boards/free"}
LONG = "가" * 101

# 종류마다 (설정, 받는가). 정상·경계·거부를 함께 둔다. 키 집합은 등록부의 '행이 될 수 있는 종류'와 같아야 한다 —
# 종류를 더하고 견본을 안 더하면 test_cases_cover_every_type 가 실패한다(대조군, D-706)
CASES: dict[str, list[tuple[dict[str, Any], bool]]] = {
    "site_brand": [
        ({"show_name": True}, True),
        ({"logo_attachment_id": 3, "logo_alt": "예시 로고", "show_name": False}, True),
        ({"logo_attachment_id": 3, "logo_alt": "  "}, False),  # 로고는 링크 이름 — 대체 텍스트 필수
        ({"show_name": False}, False),  # 빈 링크
        ({"show_name": True, "color": "red"}, False),  # 모르는 칸
    ],
    "menu": [
        ({"menu_id": 1, "label": "주 메뉴", "depth": 1}, True),
        ({"menu_id": 1, "label": " "}, False),
        ({"menu_id": 1, "label": "주 메뉴", "depth": 3}, False),
        ({"menu_id": 0, "label": "주 메뉴"}, False),
    ],
    "sub_menu": [
        ({"menu_id": 1, "label": "옆 메뉴", "show_root_title": False}, True),
        ({"menu_id": 1, "label": "가" * 51}, False),
    ],
    "breadcrumb": [({"menu_id": 1}, True), ({"menu_id": 1, "label": ""}, False)],
    "search_box": [({}, True), ({"placeholder": "가" * 50}, True), ({"placeholder": "가" * 51}, False)],
    "account": [({}, True), ({"x": 1}, False)],
    "footer_info": [
        ({"copyright": "© 예시"}, True),
        ({"lines": [{"label": "운영", "value": "예시"}] * 10}, True),
        ({"lines": [{"label": "운영", "value": "예시"}] * 11}, False),
        ({}, False),  # 아무것도 없음
        ({"lines": [{"label": " ", "value": "예시"}]}, False),
    ],
    "heading": [
        ({"text": "  회의 안내  ", "level": 4}, True),
        ({"text": "회의", "level": 1}, False),  # h1 은 페이지 제목 몫
        ({"text": "   "}, False),  # 공백만(D-119)
        ({"text": LONG}, False),
    ],
    "text": [({"source": "본문"}, True), ({"source": "가" * 10_000}, True), ({"source": "가" * 10_001}, False), ({"source": ""}, False)],
    "image": [
        ({"attachment_id": 1, "alt": "회의실"}, True),
        ({"attachment_id": 1, "decorative": True}, True),
        ({"attachment_id": 1, "alt": "회의실", "link": URL}, True),
        ({"attachment_id": 1}, False),  # 설명도 장식도 아님
        ({"attachment_id": 1, "alt": "회의실", "decorative": True}, False),
        ({"attachment_id": 1, "decorative": True, "link": URL}, False),  # 이름 없는 링크
    ],
    "banner": [
        ({"attachment_id": 1, "title": "모집 공고"}, True),
        ({"attachment_id": 1, "title": "모집", "buttons": [{"label": "보기", "link": URL}] * 3}, False),
        ({"title": "모집 공고"}, False),
    ],
    "buttons": [
        ({"items": [{"label": "공지", "link": URL}] * 6}, True),
        ({"items": [{"label": "공지", "link": URL}] * 7}, False),
        ({"items": []}, False),
        ({"items": [{"label": "가" * 31, "link": URL}]}, False),
    ],
    "link_list": [
        ({"items": [{"label": "공지", "link": URL}] * 30}, True),
        ({"items": [{"label": "공지", "link": URL}] * 31}, False),
        ({"title": "", "items": [{"label": "공지", "link": URL}]}, False),
    ],
    "video": [
        ({"url": "https://www.youtube.com/watch?v=aaaaaaaaaaa", "title": "안내"}, True),
        ({"url": "https://example.org/v.mp4", "title": "안내"}, False),  # 허용 제공자 아님
        ({"url": "https://youtu.be/aaaaaaaaaaa", "title": ""}, False),  # iframe title 필수
    ],
    "details": [
        ({"items": [{"question": "언제?", "answer": "**화요일**"}]}, True),
        ({"items": [{"question": "언제?", "answer": "![사진](attachment:1)"}]}, False),  # 답에 그림 금지
        ({"items": [{"question": "언제?", "answer": "화요일"}] * 31}, False),
    ],
    "divider": [({}, True), ({"style": "dashed"}, False)],
    "recent_posts": [
        ({"board_ids": [1, 2], "count": 20, "view": "photo", "include_pinned": False}, True),
        ({"board_ids": list(range(1, 11))}, True),
        ({"board_ids": list(range(1, 12))}, False),
        ({"board_ids": [1, 1]}, False),  # 중복
        ({"board_ids": []}, False),
        ({"board_ids": [1], "count": 21}, False),
        ({"board_ids": [1], "view": "card"}, False),
    ],
    "recent_comments": [({"board_ids": [1], "count": 1}, True), ({"board_ids": [1], "count": 0}, False)],
    "board_links": [({"board_ids": list(range(1, 31))}, True), ({"board_ids": list(range(1, 32))}, False)],
    "group": [
        ({}, True),
        ({"title": "안내", "landmark": True}, True),
        ({"landmark": True}, False),  # 랜드마크에는 이름
    ],
    "columns": [({"count": 4}, True), ({"count": 1}, False), ({"count": 5}, False)],
    "module": [
        ({"module": "board", "params": {"board_id": 1}}, True),
        ({"module": "board", "params": {"board_id": 1, "count": 4}}, False),
        ({"module": "board", "params": {"board_id": 1, "x": 1}}, False),
        ({"module": "nope", "params": {}}, False),
    ],
}


def test_cases_cover_every_type() -> None:
    assert set(CASES) == set(t.STORED_BLOCK_TYPES)


@pytest.mark.parametrize(("block_type", "config", "ok"), [(k, c, ok) for k, cases in CASES.items() for c, ok in cases])
def test_config(block_type: str, config: dict, ok: bool) -> None:
    if ok:
        t.validate_config(block_type, config)
    else:
        with pytest.raises(ValidationError):
            t.validate_config(block_type, config)


def test_strings_are_stripped() -> None:
    assert t.validate_config("heading", {"text": "  회의 안내  "}).text == "회의 안내"


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://example.org/a?b=1", True),
        ("http://example.org", True),
        ("mailto:office@example.org", True),
        ("tel:02-000-0000", True),
        ("/boards/free", True),
        ("/", True),
        ("javascript:alert(1)", False),
        ("JavaScript:alert(1)", False),
        ("data:text/html,x", False),
        ("//evil.example", False),  # 다른 사이트로 가는 상대 주소
        ("/\\evil.example", False),  # 브라우저는 역슬래시를 빗금으로 읽는다 → //evil.example(코드 검토 v5 N-1)
        ("/a\nb", False),
        ("https://example.org\njavascript:x", False),
        ("boards/free", False),
        ("https://", False),
        ("/a b", False),
        ("/" + "a" * 500, False),  # 500자 넘음
    ],
)
def test_link_target_url(url: str, ok: bool) -> None:
    config = {"items": [{"label": "링크", "link": {"kind": "url", "url": url}}]}
    if ok:
        t.validate_config("buttons", config)
    else:
        with pytest.raises(ValidationError):
            t.validate_config("buttons", config)


@pytest.mark.parametrize("block_type", ["outlet", *t.PENDING_BLOCK_TYPES, "nope"])
def test_rows_cannot_have_these_types(block_type: str) -> None:
    with pytest.raises(t.UnknownBlockType):
        t.validate_config(block_type, {})


def test_registry_shape() -> None:
    assert set(t.BLOCK_TYPES) | set(t.PENDING_BLOCK_TYPES) == set(t.SPECS)
    assert set(t.STORED_BLOCK_TYPES) == set(t.BLOCK_TYPES) - {"outlet"}
    for k, s in t.SPECS.items():
        assert s.places and set(s.places) <= {"layout", "page"}, k
        if k in t.STORED_BLOCK_TYPES:
            t.validate_config(k, s.example)  # 견본은 늘 통과
            assert t.json_schema(k)["type"] == "object", k  # 관리 화면 설정 폼(§8)
    assert t.SPECS["outlet"].places == ("layout",)
    assert t.SPECS["module"].places == ("page",)  # 페이지 본문에만(§3.4)
    assert all(m.params_model is not None for m in MODULES.values())


# ── 해결(§4.4.2) ─────────────────────────────────────────

IMG = ImageSource("/media/ab/x.w{w}.webp", 640, 480, thumbs_ready=True)
LOOKUP = Lookup(site_name="예시 사이트", page_paths={7: "/about"}, board_slugs={3: "notice"}, images={1: IMG})
PAGE = {"kind": "page", "page_id": 7}
GONE_PAGE = {"kind": "page", "page_id": 99}


def test_link_resolution() -> None:
    assert link(t.PageLink(kind="page", page_id=7), LOOKUP) == {"href": "/about", "new_window": False}
    assert link(t.BoardLink(kind="board", board_id=3, new_window=True), LOOKUP) == {"href": "/boards/notice", "new_window": True}
    assert link(t.BoardLink(kind="board", board_id=4), LOOKUP) is None  # 지워짐·비공개
    assert link(None, LOOKUP) is None


def test_missing_targets_drop_items_then_block() -> None:
    items = [{"label": "소개", "link": PAGE}, {"label": "옛 페이지", "link": GONE_PAGE}]
    assert resolve("buttons", {"items": items}, LOOKUP) == {"items": [{"label": "소개", "href": "/about", "new_window": False}]}
    assert resolve("buttons", {"items": [items[1]]}, LOOKUP) is None  # 남은 항목이 없으면 그리지 않는다
    assert resolve("link_list", {"items": [items[1]]}, LOOKUP) is None


def test_image_rules() -> None:
    out = resolve("image", {"attachment_id": 1, "alt": "회의실", "link": GONE_PAGE}, LOOKUP)
    assert out is not None and out["link"] is None  # 링크만 빠진다
    assert out["image"]["src"] == "/media/ab/x.w640.webp" and "1280w" in out["image"]["srcset"]
    assert resolve("image", {"attachment_id": 2, "alt": "없는 그림"}, LOOKUP) is None
    assert resolve("banner", {"attachment_id": 2, "title": "모집"}, LOOKUP) is None
    banner = resolve("banner", {"attachment_id": 1, "title": "모집"}, LOOKUP)
    assert banner is not None and banner["image"]["alt"] == ""  # 배너 그림은 장식


def test_pending_thumbnail_never_exposes_original() -> None:
    lookup = Lookup(site_name="예시", images={1: ImageSource("/api/attachments/1/thumb?w={w}", 640, 480, thumbs_ready=False)})
    img = resolve("image", {"attachment_id": 1, "alt": "회의실"}, lookup)["image"]
    assert img == {"alt": "회의실", "width": 640, "height": 480, "pending": True}


def test_site_brand() -> None:
    assert resolve("site_brand", {}, LOOKUP) == {"href": "/", "name": "예시 사이트", "logo": None}
    # 로고가 사라지고 이름도 숨겼으면 빈 링크가 되므로 그리지 않는다
    assert resolve("site_brand", {"logo_attachment_id": 2, "logo_alt": "로고", "show_name": False}, LOOKUP) is None


def test_text_uses_post_markdown_and_block_images() -> None:
    src = "**굵게**\n\n![회의실](attachment:1)\n\n<script>x</script>"
    html = resolve("text", {"source": src}, LOOKUP, attachment_ids=(1,))["html"]
    assert "<strong>굵게</strong>" in html and 'src="/media/ab/x.w640.webp"' in html
    assert "<script>" not in html  # 원문 HTML 은 꺼져 있다(글과 같은 변환·정화)
    # 이 블록의 첨부가 아닌 그림이면 그리지 않는다(경고 기록)
    assert resolve("text", {"source": "![x](attachment:1)"}, LOOKUP, attachment_ids=()) is None


def test_video_embed() -> None:
    out = resolve("video", {"url": "https://youtu.be/aaaaaaaaaaa", "title": "안내"}, LOOKUP)
    assert out == {"title": "안내", "embed_url": "https://www.youtube-nocookie.com/embed/aaaaaaaaaaa"}


@pytest.mark.parametrize("block_type", sorted(NOT_YET))
def test_not_yet_types_raise(block_type: str) -> None:
    with pytest.raises(NotImplementedError):
        resolve(block_type, {}, LOOKUP)


# ── 생성 파일 ────────────────────────────────────────────


def test_generated_file_is_current() -> None:
    # 원본과 다르면: cd backend && uv run python -m scripts.gen_blocks 실행 뒤 커밋
    assert TARGET.read_text(encoding="utf-8") == render()
