"""본문 의미 토큰 — 설계도 §8.2·§8.3 의 원본.

nh3 정화·마크다운 변환·렌더·(생성 JSON 을 통해) 프런트 에디터·스킨이 모두 이 값을 쓴다.
값을 바꾸면 `python3 scripts/gen_editor_tokens.py` 로 frontend/lib/editor/tokens.gen.json 을 다시 만든다(CI 가 비교).
이 파일은 표준 라이브러리만 쓴다 — CI 가 의존성 설치 없이 읽는다.
"""

import re

# 정화 정책 버전 — 아래 허용 목록을 바꾸면 올리고, 재정화 작업이 옛 글을 다시 만든다(§4.3 sanitizer_version)
SANITIZER_VERSION = 1

ALIGN = ("left", "center", "right", "justify")
LEADING = ("tight", "normal", "relaxed", "loose")
# 색 이름은 의미 없는 팔레트 이름 — 실제 색은 스킨 CSS 가 정한다. 제목 꾸밈(title_color)도 같은 토큰
COLORS = ("gray", "red", "orange", "yellow", "green", "blue", "purple", "pink")
FONTS = ("sans", "serif", "mono")
TEXT_SIZES = ("sm", "md", "lg", "xl", "2xl")
MARKS = ("yellow", "green", "blue", "pink")
IMAGE_WIDTHS = ("s", "m", "l", "full")
TABLE_SCOPES = ("row", "col")
URL_SCHEMES = ("http", "https", "mailto")
LINK_REL = "noopener noreferrer nofollow ugc"

# 동영상 제공자 — 항목을 더해 확장한다(§8.2). 지금은 유튜브만
VIDEO_PROVIDERS = {
    "youtube": {
        "id_pattern": r"^[A-Za-z0-9_-]{11}$",
        "url_patterns": [
            r"^https?://(?:www\.|m\.)?youtube\.com/watch\?(?:[^#\s]*&)?v=([A-Za-z0-9_-]{11})(?:[&#][^\s]*)?$",
            r"^https?://youtu\.be/([A-Za-z0-9_-]{11})(?:[?#][^\s]*)?$",
            r"^https?://(?:www\.)?youtube\.com/(?:shorts|embed|live)/([A-Za-z0-9_-]{11})(?:[?#][^\s]*)?$",
        ],
        "embed_url": "https://www.youtube-nocookie.com/embed/{id}",
        "title": "YouTube 동영상",
    },
}

# 허용 태그 → 허용 속성. data-* 값은 아래 ATTRIBUTE_VALUES 로 검증한다
TAGS: dict[str, tuple[str, ...]] = {
    "p": ("data-align", "data-leading"),
    "h2": ("data-align", "data-leading"),
    "h3": ("data-align", "data-leading"),
    "br": (),
    "strong": (),
    "em": (),
    "u": (),
    "s": (),
    "sub": (),
    "sup": (),
    "code": (),
    "pre": (),
    "span": ("data-color", "data-font", "data-text-size"),
    "mark": ("data-mark",),
    "ul": (),
    "ol": ("start",),
    "li": (),
    "blockquote": (),
    "hr": (),
    "a": ("href",),
    "figure": ("data-attachment-id", "data-width", "data-align"),
    "img": ("alt",),
    "figcaption": (),
    "table": (),
    "thead": (),
    "tbody": (),
    "tr": (),
    "th": ("scope", "colspan", "rowspan"),
    "td": ("colspan", "rowspan"),
    "div": ("data-embed", "data-video-id"),
}

_POSITIVE_INT = r"^[1-9][0-9]{0,8}$"
_SPAN = r"^[1-9][0-9]?$"  # colspan/rowspan 1~99

# 속성 → 허용 값(튜플) 또는 정규식(문자열)
ATTRIBUTE_VALUES: dict[str, tuple[str, ...] | str] = {
    "data-align": ALIGN,
    "data-leading": LEADING,
    "data-color": COLORS,
    "data-font": FONTS,
    "data-text-size": TEXT_SIZES,
    "data-mark": MARKS,
    "data-width": IMAGE_WIDTHS,
    "data-attachment-id": _POSITIVE_INT,
    "data-embed": tuple(VIDEO_PROVIDERS),
    "data-video-id": r"^[A-Za-z0-9_-]{11}$",
    "start": _POSITIVE_INT,
    "scope": TABLE_SCOPES,
    "colspan": _SPAN,
    "rowspan": _SPAN,
}


def attribute_value_ok(attr: str, value: str) -> bool:
    rule = ATTRIBUTE_VALUES.get(attr)
    if rule is None:
        return True  # href·alt — href 는 nh3 의 url_schemes 가 검사한다
    if isinstance(rule, tuple):
        return value in rule
    return re.fullmatch(rule, value) is not None


def as_json() -> dict:
    """프런트가 읽는 생성 파일의 내용."""
    return {
        "sanitizerVersion": SANITIZER_VERSION,
        "align": list(ALIGN),
        "leading": list(LEADING),
        "colors": list(COLORS),
        "fonts": list(FONTS),
        "textSizes": list(TEXT_SIZES),
        "marks": list(MARKS),
        "imageWidths": list(IMAGE_WIDTHS),
        "urlSchemes": list(URL_SCHEMES),
        "videoProviders": {
            name: {"idPattern": p["id_pattern"], "urlPatterns": p["url_patterns"]}
            for name, p in VIDEO_PROVIDERS.items()
        },
        "tags": {tag: list(attrs) for tag, attrs in TAGS.items()},
    }
