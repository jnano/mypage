"""블록 종류의 원본 — 홈블록 설계도 §2.2·§4.3·§4.4.

종류마다 설정 형식(Pydantic, extra=forbid)·갈래·놓을 수 있는 곳·견본을 이 한 곳에 둔다. DB CHECK(`blocks.type`)·
관리 화면(JSON Schema)·생성 파일(blocks.gen.json)이 여기서 나온다. 개수·순서를 시험에 하드코딩하지 않는다(D-706).
"""

import re
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    ValidationInfo,
    field_validator,
    model_validator,
)

from app.blocks.modules import MODULES
from app.editor import tokens
from app.editor.markdown import MarkdownInputError, markdown_to_html

# ── 공용 칸 ──────────────────────────────────────────────


def trimmed(min_length: int, max_length: int):
    # 앞뒤 공백을 지운 뒤 길이 검사 — 공백만이면 빈 값(D-119)
    return Annotated[str, StringConstraints(strip_whitespace=True, min_length=min_length, max_length=max_length)]


Id = Annotated[int, Field(ge=1)]


def _unique(ids: list[int]) -> list[int]:
    if len(set(ids)) != len(ids):
        raise ValueError("같은 항목을 두 번 고를 수 없습니다")
    return ids


def _ids(min_length: int, max_length: int):
    return Annotated[list[Id], Field(min_length=min_length, max_length=max_length), AfterValidator(_unique)]


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid")


# 사이트 안 경로(/ 로 시작) 또는 허용 스킴. javascript:·data: 등은 형식에서 걸러진다(§4.4·§9).
# `//`·`/\` 로 시작하면 다른 사이트로 가는 상대 주소다 — 브라우저(WHATWG URL)는 역슬래시를 빗금으로 읽는다(코드 검토 v5 N-1)
_URL = re.compile(r"(?:https?://[^\s/]+[^\s]*|mailto:[^\s]+|tel:[0-9+\-() ]+|/(?![/\\])[^\s]*)", re.IGNORECASE)


def _url(value: str) -> str:
    if not _URL.fullmatch(value):  # fullmatch — `$` 는 끝 줄바꿈 앞에서도 맞는다
        raise ValueError("링크는 https://·http://·mailto:·tel: 또는 / 로 시작하는 사이트 안 주소만 됩니다")
    return value


class PageLink(_Config):
    kind: Literal["page"]
    page_id: Id
    new_window: bool = False


class BoardLink(_Config):
    kind: Literal["board"]
    board_id: Id
    new_window: bool = False


class UrlLink(_Config):
    kind: Literal["url"]
    url: Annotated[trimmed(1, 500), AfterValidator(_url)]
    new_window: bool = False


LinkTarget = Annotated[PageLink | BoardLink | UrlLink, Field(discriminator="kind")]


class Button(_Config):
    label: trimmed(1, 30)
    link: LinkTarget


# ── 종류별 설정(§4.4.1) ──────────────────────────────────


class SiteBrand(_Config):
    logo_attachment_id: Id | None = None
    logo_alt: trimmed(0, 100) = ""
    show_name: bool = True

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.logo_attachment_id is not None and not self.logo_alt:
            raise ValueError("로고에는 대체 텍스트가 필요합니다(로고가 링크 이름이 됩니다)")
        if self.logo_attachment_id is None and not self.show_name:
            raise ValueError("로고나 사이트 이름 중 하나는 보여야 합니다")
        return self


class Menu(_Config):
    menu_id: Id
    label: trimmed(1, 50)
    depth: Literal[1, 2] = 2


class SubMenu(_Config):
    menu_id: Id
    label: trimmed(1, 50)
    show_root_title: bool = True


class Breadcrumb(_Config):
    menu_id: Id
    label: trimmed(1, 50) = "현재 위치"


class SearchBox(_Config):
    placeholder: trimmed(0, 50) = "검색어"


class Empty(_Config):
    pass


class FooterLine(_Config):
    label: trimmed(1, 30)
    value: trimmed(1, 200)


class FooterInfo(_Config):
    lines: Annotated[list[FooterLine], Field(max_length=10)] = []
    copyright: trimmed(1, 200) | None = None

    @model_validator(mode="after")
    def _check(self) -> Self:
        if not self.lines and self.copyright is None:
            raise ValueError("줄이나 저작권 문구 중 하나는 있어야 합니다")
        return self


class Heading(_Config):
    text: trimmed(1, 100)
    level: Literal[2, 3, 4] = 2


class Text(_Config):
    source: trimmed(1, 10_000)


class Image(_Config):
    attachment_id: Id
    alt: trimmed(0, 300) = ""
    decorative: bool = False
    link: LinkTarget | None = None

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.decorative and self.alt:
            raise ValueError("장식 그림은 대체 텍스트를 비웁니다")
        if not self.decorative and not self.alt:
            raise ValueError("그림 설명(대체 텍스트)이 필요합니다 — 꾸밈용이면 '장식'을 고릅니다")
        if self.decorative and self.link is not None:
            raise ValueError("장식 그림에는 링크를 걸 수 없습니다(이름 없는 링크가 됩니다)")
        return self


class Banner(_Config):
    attachment_id: Id
    title: trimmed(1, 100)
    description: trimmed(1, 300) | None = None
    buttons: Annotated[list[Button], Field(max_length=2)] = []


class Buttons(_Config):
    items: Annotated[list[Button], Field(min_length=1, max_length=6)]


class LinkItem(_Config):
    label: trimmed(1, 100)
    link: LinkTarget


class LinkList(_Config):
    title: trimmed(1, 100) | None = None
    items: Annotated[list[LinkItem], Field(min_length=1, max_length=30)]


_VIDEO_URLS = [
    (name, re.compile(pattern))
    for name, provider in tokens.VIDEO_PROVIDERS.items()
    for pattern in provider["url_patterns"]
]


def video_id(url: str) -> tuple[str, str] | None:
    """허용 제공자의 주소면 (제공자, 영상 id) — 글 본문의 동영상 판정과 같은 목록(본 §8.2)"""
    for name, pattern in _VIDEO_URLS:
        if m := pattern.match(url):
            return name, m.group(1)
    return None


def _video_url(value: str) -> str:
    if video_id(value) is None:
        raise ValueError("허용된 동영상 주소가 아닙니다")
    return value


class Video(_Config):
    url: Annotated[trimmed(1, 500), AfterValidator(_video_url)]
    title: trimmed(1, 100)


def _no_images(value: str) -> str:
    try:
        markdown_to_html(value)  # 허용 첨부 없음 — 그림이 있으면 MarkdownInputError
    except MarkdownInputError:
        raise ValueError("답에는 그림을 넣을 수 없습니다") from None
    return value


class DetailsItem(_Config):
    question: trimmed(1, 200)
    answer: Annotated[trimmed(1, 5_000), AfterValidator(_no_images)]


class Details(_Config):
    items: Annotated[list[DetailsItem], Field(min_length=1, max_length=30)]


class RecentPosts(_Config):
    title: trimmed(1, 100) | None = None
    board_ids: _ids(1, 10)
    count: Annotated[int, Field(ge=1, le=20)] = 5
    view: Literal["list", "photo"] = "list"
    include_pinned: bool = True


class RecentComments(_Config):
    title: trimmed(1, 100) | None = None
    board_ids: _ids(1, 10)
    count: Annotated[int, Field(ge=1, le=20)] = 5


class BoardLinks(_Config):
    title: trimmed(1, 100) | None = None
    board_ids: _ids(1, 30)


class Group(_Config):
    title: trimmed(1, 100) | None = None
    landmark: bool = False

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.landmark and self.title is None:
            raise ValueError("랜드마크로 내보내려면 제목(이름)이 필요합니다")
        return self


class Columns(_Config):
    count: Annotated[int, Field(ge=2, le=4)]


class Module(_Config):
    module: str
    params: dict[str, Any]

    @field_validator("module")
    @classmethod
    def _registered(cls, value: str) -> str:
        spec = MODULES.get(value)
        if spec is None or not spec.available:
            raise ValueError("등록되지 않은 모듈입니다")
        return value

    # 칸 검증기라 모듈 설정의 오류 위치가 params 아래로 온다(`config.params.board_id` — 관리 화면이 칸 옆에 보인다, 걸음 7)
    @field_validator("params")
    @classmethod
    def _params(cls, value: dict[str, Any], info: ValidationInfo) -> dict[str, Any]:
        spec = MODULES.get(info.data.get("module", ""))
        if spec is None:  # 모듈 키 오류는 위에서 낸다
            return value
        return spec.params_model.model_validate(value).model_dump()


# ── 등록부 ───────────────────────────────────────────────

BlockGroup = Literal["site", "content", "dynamic", "structure", "empty"]
Place = Literal["layout", "page"]


@dataclass(frozen=True)
class BlockSpec:
    label: str
    group: BlockGroup
    places: tuple[Place, ...]
    model: type[BaseModel] | None  # None = 설정 없음·행 없음(outlet)
    example: dict[str, Any] | None  # 견본 — 시험·생성 파일·개발 견본 화면이 쓴다
    available: bool = True


L, P, LP = ("layout",), ("page",), ("layout", "page")

SPECS: dict[str, BlockSpec] = {
    # 사이트
    "site_brand": BlockSpec("사이트 이름·로고", "site", L, SiteBrand, {"show_name": True}),
    "menu": BlockSpec("주 메뉴", "site", L, Menu, {"menu_id": 1, "label": "주 메뉴"}),
    "sub_menu": BlockSpec("옆 메뉴", "site", L, SubMenu, {"menu_id": 1, "label": "옆 메뉴"}),
    "breadcrumb": BlockSpec("경로 표시", "site", L, Breadcrumb, {"menu_id": 1}),
    "search_box": BlockSpec("검색", "site", LP, SearchBox, {}),
    "account": BlockSpec("계정", "site", L, Empty, {}),
    "footer_info": BlockSpec(
        "바닥 정보",
        "site",
        L,
        FooterInfo,
        {"lines": [{"label": "운영", "value": "예시 운영 주체"}, {"label": "연락처", "value": "02-000-0000"}], "copyright": "© 예시 사이트"},
    ),
    # 콘텐츠
    "heading": BlockSpec("제목", "content", LP, Heading, {"text": "회의 안내", "level": 2}),
    "text": BlockSpec(
        "글", "content", LP, Text, {"source": "이번 주 **회의**는 화요일입니다.\n\n- 장소: 회의실\n- 시간: 오후 3시"}
    ),
    "image": BlockSpec("그림", "content", LP, Image, {"attachment_id": 1, "alt": "회의실 사진"}),
    "banner": BlockSpec(
        "배너",
        "content",
        P,
        Banner,
        {
            "attachment_id": 1,
            "title": "모집 공고",
            "description": "함께할 분을 찾습니다.",
            "buttons": [{"label": "자세히 보기", "link": {"kind": "url", "url": "/boards/notice"}}],
        },
    ),
    "buttons": BlockSpec(
        "단추 모음",
        "content",
        LP,
        Buttons,
        {
            "items": [
                {"label": "공지", "link": {"kind": "url", "url": "/boards/notice"}},
                {"label": "예시 사이트", "link": {"kind": "url", "url": "https://example.org", "new_window": True}},
            ]
        },
    ),
    "link_list": BlockSpec(
        "링크 목록",
        "content",
        LP,
        LinkList,
        {
            "title": "바로가기",
            "items": [
                {"label": "자유게시판", "link": {"kind": "url", "url": "/boards/free"}},
                {"label": "예시 사이트", "link": {"kind": "url", "url": "https://example.org", "new_window": True}},
            ],
        },
    ),
    "video": BlockSpec(
        "동영상", "content", P, Video, {"url": "https://youtu.be/aaaaaaaaaaa", "title": "안내 영상"}
    ),
    "details": BlockSpec(
        "자주 묻는 질문",
        "content",
        P,
        Details,
        {"items": [{"question": "회의는 언제인가요?", "answer": "매주 **화요일** 오후입니다."}]},
    ),
    "divider": BlockSpec("구분선", "content", LP, Empty, {}),
    # 동적
    "recent_posts": BlockSpec("최근 글", "dynamic", LP, RecentPosts, {"title": "최근 글", "board_ids": [1]}),
    "recent_comments": BlockSpec(
        "최근 댓글", "dynamic", LP, RecentComments, {"title": "최근 댓글", "board_ids": [1]}
    ),
    "board_links": BlockSpec("게시판 바로가기", "dynamic", LP, BoardLinks, {"board_ids": [1]}),
    # 구조
    "group": BlockSpec("묶음", "structure", LP, Group, {"title": "안내", "landmark": True}),
    "columns": BlockSpec("칸 나누기", "structure", P, Columns, {"count": 2}),
    # 빈 블록
    "outlet": BlockSpec("본문 자리", "empty", L, None, None),
    "module": BlockSpec(
        "모듈 자리", "empty", P, Module, {"module": "board", "params": {"board_id": 1, "view": None, "count": 10}}
    ),
    # 2단계 대기(§2.2) — 종류 표에 available: false 로만
    "popular_posts": BlockSpec("인기 글", "dynamic", LP, None, None, available=False),
    "visitor_count": BlockSpec("방문자 수", "dynamic", LP, None, None, available=False),
    "popup": BlockSpec("팝업", "content", L, None, None, available=False),
    "map": BlockSpec("지도", "content", P, None, None, available=False),
    "calendar": BlockSpec("일정", "content", P, None, None, available=False),
}

# 지금 쓸 수 있는 종류(§2.2 표 순서). outlet 은 렌더러가 놓는 자리라 행이 없다(§3.1)
BLOCK_TYPES: tuple[str, ...] = tuple(t for t, s in SPECS.items() if s.available)

# 2단계 대기. 행을 만들 수 없다 — 쓸 수 있게 될 때 available 을 켜고 CHECK 를 바꾸는 마이그레이션을 함께 낸다
PENDING_BLOCK_TYPES: tuple[str, ...] = tuple(t for t, s in SPECS.items() if not s.available)

# 행이 될 수 있는 종류 = DB CHECK 의 목록
STORED_BLOCK_TYPES: tuple[str, ...] = tuple(t for t in BLOCK_TYPES if t != "outlet")

# 동적 블록 — 주인당 상한(limits.MAX_DYNAMIC_BLOCKS)에 세는 것(§4.3). module 도 데이터를 부르므로 센다
DYNAMIC_BLOCK_TYPES: tuple[str, ...] = (*(t for t in BLOCK_TYPES if SPECS[t].group == "dynamic"), "module")

# 틀의 영역(§3.1) — 스킨 계약(data-region). 운영자가 늘리지 않는다
REGIONS: tuple[str, ...] = ("header", "nav", "top", "aside", "bottom", "footer")

AUDIENCES: tuple[str, ...] = ("all", "guest", "member")

# 메뉴 항목의 링크 종류(§4.5). none = 링크 없는 묶음 제목
MENU_LINK_KINDS: tuple[str, ...] = ("page", "board", "url", "none")


class UnknownBlockType(ValueError):
    pass


def validate_config(block_type: str, config: Any) -> BaseModel:
    """저장할 설정을 그 종류의 형식으로 검증한다. 행이 될 수 없는 종류(outlet·대기)는 거부"""
    spec = SPECS.get(block_type)
    if spec is None or block_type not in STORED_BLOCK_TYPES or spec.model is None:
        raise UnknownBlockType(block_type)
    return spec.model.model_validate(config)


def json_schema(block_type: str) -> dict[str, Any] | None:
    """관리 화면 설정 폼용 — 칸 명세를 프런트에 따로 쓰지 않는다(§8)"""
    spec = SPECS[block_type]
    return None if spec.model is None else TypeAdapter(spec.model).json_schema()
