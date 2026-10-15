"""본문 처리 한 곳 — 작성·수정·미리보기가 같이 쓴다(§8.4).

원문(마크다운) 또는 리치 HTML → 정본(content_html) → 읽기용(content_rendered) → 검색용 공백 제거본.
막히는 작업이라 스레드 한도 'sanitize' 안에서 돈다(§3.1-3).
"""

import unicodedata
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Literal

from app.core.problems import Problem
from app.core.threads import run_in_thread
from app.editor import tokens
from app.editor.markdown import MarkdownInputError, markdown_to_html
from app.editor.render import ImageSource, render_content
from app.editor.sanitize import plain_text, sanitize_html

ContentFormat = Literal["rich", "markdown"]


@dataclass(frozen=True)
class Content:
    format: ContentFormat
    source: str | None  # 마크다운 원문(markdown 글만)
    html: str  # 정본
    rendered: str  # 읽기용
    text: str  # 태그를 지운 본문
    sanitizer_version: int = tokens.SANITIZER_VERSION


def compact(text: str) -> str:
    """검색 정규화(§9) — NFKC + casefold + 공백 제거. 색인(공백 제거본·2글자 토큰)과 검색어가 같은 함수를 쓴다."""
    return "".join(unicodedata.normalize("NFKC", text).casefold().split())


def _build(
    fmt: ContentFormat,
    raw: str,
    attachment_ids: Collection[int],
    images: Mapping[int, ImageSource],
) -> Content:
    if fmt == "markdown":
        html = markdown_to_html(raw, attachment_ids)
        source: str | None = raw
    else:
        html = sanitize_html(raw)
        source = None
    text = plain_text(html)
    if not text and "<figure" not in html and "data-embed" not in html:
        raise MarkdownInputError("본문이 비어 있습니다")
    return Content(fmt, source, html, render_content(html, images), text)


async def build_content(
    fmt: ContentFormat,
    raw: str,
    attachment_ids: Collection[int] = (),
    images: Mapping[int, ImageSource] | None = None,
) -> Content:
    try:
        return await run_in_thread("sanitize", _build, fmt, raw, attachment_ids, images or {})
    except MarkdownInputError as e:
        raise Problem(
            422,
            "validation_error",
            "입력값이 올바르지 않습니다",
            errors=[{"field": "content", "message": e.message}],
        ) from None
