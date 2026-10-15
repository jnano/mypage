"""마크다운 → 의미 토큰 HTML — 설계도 §8.4. 변환기는 서버 이 한 곳뿐이다(저장·미리보기 공용).

- CommonMark + 표(GFM) + 취소선. 원문 안의 HTML 은 끈다(html=False). 결과는 nh3 를 그대로 거친다.
- 제목은 h2·h3 만: `#` → h2, `####` 이하 → h3.
- 이미지 `![설명](attachment:123)` → figure 토큰. id 는 그 글의 첨부 목록과 대조한다(외부 이미지 불허).
- 한 줄에 동영상 주소만 있으면 동영상 토큰(제공자 목록 §8.2).
"""

import re
from collections.abc import Collection
from dataclasses import dataclass

from markdown_it import MarkdownIt
from markdown_it.token import Token

from app.editor import tokens
from app.editor.sanitize import sanitize_html

_ATTACHMENT_SRC = re.compile(r"^attachment:([1-9][0-9]{0,8})$")
_VIDEO_URLS = [
    (name, re.compile(pattern))
    for name, provider in tokens.VIDEO_PROVIDERS.items()
    for pattern in provider["url_patterns"]
]


@dataclass
class MarkdownInputError(Exception):
    message: str


def _video_id(text: str) -> tuple[str, str] | None:
    for name, pattern in _VIDEO_URLS:
        if m := pattern.match(text.strip()):
            return name, m.group(1)
    return None


def _render_image(self, toks, idx, options, env) -> str:
    token = toks[idx]
    attachment_id = token.meta["attachment_id"]
    alt = self.renderInlineAsText(token.children or [], options, env)
    return (
        f'<figure data-attachment-id="{attachment_id}" data-width="m">'
        f'<img alt="{_escape_attr(alt)}"></figure>'
    )


def _render_video(self, toks, idx, options, env) -> str:
    meta = toks[idx].meta
    return f'<div data-embed="{meta["provider"]}" data-video-id="{meta["video_id"]}"></div>\n'


def _escape_attr(value: str) -> str:
    return value.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")


def _build() -> MarkdownIt:
    md = MarkdownIt("commonmark", {"html": False}).enable(["table", "strikethrough"])
    md.add_render_rule("image", _render_image)
    md.add_render_rule("video_embed", _render_video)
    return md


_md = _build()


def _inline_only(inline: Token) -> list[Token]:
    """문단 안의 의미 있는 자식(줄바꿈 제외)."""
    return [c for c in inline.children or [] if c.type not in ("softbreak", "hardbreak")]


def _transform(toks: list[Token], allowed_attachment_ids: Collection[int]) -> list[Token]:
    out: list[Token] = []
    in_thead = False
    i = 0
    while i < len(toks):
        t = toks[i]
        if t.type in ("heading_open", "heading_close"):
            t.tag = "h2" if t.tag in ("h1", "h2") else "h3"
        elif t.type == "thead_open":
            in_thead = True
        elif t.type == "thead_close":
            in_thead = False
        elif t.type == "th_open":
            t.attrs = {"scope": "col" if in_thead else "row"}
        elif t.type in ("td_open",):
            t.attrs = {}
        elif t.type == "inline":
            for child in t.children or []:
                if child.type == "image":
                    m = _ATTACHMENT_SRC.match(str(child.attrGet("src") or ""))
                    if m is None:
                        raise MarkdownInputError("이미지는 첨부 파일만 넣을 수 있습니다(attachment:번호)")
                    attachment_id = int(m.group(1))
                    if attachment_id not in allowed_attachment_ids:
                        raise MarkdownInputError(f"이 글의 첨부가 아닌 이미지입니다: {attachment_id}")
                    child.meta["attachment_id"] = attachment_id

        # 문단 단위 변환: [paragraph_open, inline, paragraph_close]
        if t.type == "paragraph_open" and i + 2 < len(toks):
            inline = toks[i + 1]
            kids = _inline_only(inline)
            texts = [c for c in kids if c.type == "text"]
            # 동영상: 문단이 주소 하나(일반 텍스트 또는 <자동 링크>)뿐일 때
            only_url = (
                (len(kids) == 1 and kids[0].type == "text")
                or ([c.type for c in kids] == ["link_open", "text", "link_close"])
            )
            if only_url and texts and (video := _video_id(texts[0].content)):
                embed = Token("video_embed", "div", 0)
                embed.meta = {"provider": video[0], "video_id": video[1]}
                embed.block = True
                out.append(embed)
                i += 3
                continue
            # 이미지만 있는 문단은 <p> 없이 figure 만(figure 는 p 안에 올 수 없다)
            if kids and all(c.type == "image" for c in kids):
                t.hidden = True
                toks[i + 2].hidden = True
        out.append(t)
        i += 1
    return out


def markdown_to_html(source: str, allowed_attachment_ids: Collection[int] = ()) -> str:
    """마크다운 원문 → 정화된 의미 토큰 HTML(content_html)."""
    env: dict = {}
    toks = _transform(_md.parse(source, env), allowed_attachment_ids)
    return sanitize_html(_md.renderer.render(toks, _md.options, env))
