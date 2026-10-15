"""본문 HTML 정화 — nh3 한 곳(§11). 정본 content_html 은 이 함수를 거친 의미 토큰 HTML 이다."""

import re
from html import unescape

import nh3

from app.editor import tokens

_TAGS = set(tokens.TAGS)
# "*" 를 빈 집합으로 명시 — nh3 는 기본으로 모든 태그에 lang·title 을 허용한다(실측)
_ATTRIBUTES = {"*": set()} | {tag: set(attrs) for tag, attrs in tokens.TAGS.items()}
_ALLOWED_PAIRS = {(tag, attr) for tag, attrs in tokens.TAGS.items() for attr in attrs}


def _attribute_filter(tag: str, attr: str, value: str) -> str | None:
    # rel 은 nh3 가 link_rel 로 넣은 값만 남긴다(입력의 rel 은 버린다)
    if tag == "a" and attr == "rel":
        return value if value == tokens.LINK_REL else None
    if (tag, attr) not in _ALLOWED_PAIRS or not tokens.attribute_value_ok(attr, value):
        return None
    return value


_cleaner = nh3.Cleaner(
    tags=_TAGS,
    clean_content_tags={"script", "style", "iframe", "object", "embed", "template", "noscript"},
    attributes=_ATTRIBUTES,
    attribute_filter=_attribute_filter,
    url_schemes=set(tokens.URL_SCHEMES),
    url_relative="deny",
    link_rel=tokens.LINK_REL,
    strip_comments=True,
)


def sanitize_html(html: str) -> str:
    return _cleaner.clean(html)


_BLOCK_END = re.compile(r"</(?:p|h2|h3|li|blockquote|pre|td|th|figcaption|div)>|<br>|<hr>")


def plain_text(html: str) -> str:
    """태그를 모두 지운 본문 — 검색 공백 제거본·설명문용. 블록 경계는 공백 하나로."""
    spaced = _BLOCK_END.sub(r" \g<0>", html)
    return " ".join(unescape(nh3.clean(spaced, tags=set())).split())
