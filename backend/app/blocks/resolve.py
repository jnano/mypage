"""블록 설정 → 그리기용 모양(해결된 데이터) — 홈블록 설계도 §4.4.2.

순수 함수다. 조회 결과(Lookup)는 부르는 쪽(묶음 응답, 걸음 5)이 쿼리로 채운다 — 여기서는 DB 를 읽지 않는다.
Lookup 에는 보는 사람(공개 묶음이면 비회원)이 볼 수 있는 대상만 들어 있다. 없는 대상을 가리키는 링크·그림은
빼고, 남은 것이 없으면 블록을 그리지 않는다(None) — 읽는 쪽 셋 중 '렌더 때 건너뛴다'(G-05).
"""

import logging
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from app.blocks import types as t
from app.editor import tokens
from app.editor.markdown import MarkdownInputError, markdown_to_html
from app.editor.render import THUMB_WIDTHS, ImageSource, render_content

log = logging.getLogger(__name__)

View = dict[str, Any]


@dataclass(frozen=True)
class Lookup:
    site_name: str
    page_paths: Mapping[int, str] = field(default_factory=dict)  # 게시된·볼 수 있는 페이지 id → 주소
    board_slugs: Mapping[int, str] = field(default_factory=dict)  # 사용 중·볼 수 있는 게시판 id → slug
    images: Mapping[int, ImageSource] = field(default_factory=dict)  # 블록 그림 첨부 id → 주소


# 걸음 4(메뉴)·5(동적)·6(모듈)에서 해결한다. outlet 은 행이 없다
NOT_YET = frozenset({"menu", "sub_menu", "breadcrumb", "recent_posts", "recent_comments", "board_links", "module", "outlet"})


def link(target: BaseModel | None, lookup: Lookup) -> View | None:
    match target:
        case t.PageLink(page_id=pid):
            href = lookup.page_paths.get(pid)
        case t.BoardLink(board_id=bid):
            href = f"/boards/{slug}" if (slug := lookup.board_slugs.get(bid)) else None
        case t.UrlLink(url=url):
            href = url
        case _:
            return None
    return None if href is None else {"href": href, "new_window": target.new_window}


def image(attachment_id: int, alt: str, lookup: Lookup) -> View | None:
    img = lookup.images.get(attachment_id)
    if img is None:
        return None
    out: View = {"alt": alt, "width": img.width, "height": img.height}
    if not img.thumbs_ready:
        return out | {"pending": True}  # 원본을 내보내지 않는다(본 §12.1)
    return out | {
        "src": img.thumb_url.format(w=640),
        "srcset": ", ".join(f"{img.thumb_url.format(w=w)} {w}w" for w in THUMB_WIDTHS),
    }


def _links(items: list[Any], lookup: Lookup) -> list[View]:
    out = []
    for item in items:
        if (target := link(item.link, lookup)) is not None:
            out.append({"label": item.label, **target})
    return out


def _markdown(source: str, lookup: Lookup, attachment_ids: Collection[int]) -> str:
    return render_content(markdown_to_html(source, attachment_ids), lookup.images)


def resolve(block_type: str, config: Any, lookup: Lookup, *, attachment_ids: Collection[int] = ()) -> View | None:
    """그릴 모양 또는 None(그리지 않음). attachment_ids = 이 블록의 첨부(text 의 그림 허용 목록)"""
    if block_type in NOT_YET:
        raise NotImplementedError(block_type)
    c = t.validate_config(block_type, config)
    match c:
        case t.SiteBrand():
            logo = image(c.logo_attachment_id, c.logo_alt, lookup) if c.logo_attachment_id else None
            name = lookup.site_name if c.show_name else None
            return None if logo is None and name is None else {"href": "/", "name": name, "logo": logo}
        case t.SearchBox():
            return {"action": "/search", "placeholder": c.placeholder}
        case t.FooterInfo():
            return c.model_dump()
        case t.Heading():
            return c.model_dump()
        case t.Text():
            try:
                return {"html": _markdown(c.source, lookup, attachment_ids)}
            except MarkdownInputError as e:
                log.warning("text 블록을 그리지 못함: %s", e.message)
                return None
        case t.Image():
            img = image(c.attachment_id, c.alt, lookup)
            return None if img is None else {"image": img, "link": link(c.link, lookup)}
        case t.Banner():
            img = image(c.attachment_id, "", lookup)  # 배너 그림은 늘 장식(§4.4.1)
            if img is None:
                return None
            return {"image": img, "title": c.title, "description": c.description, "buttons": _links(c.buttons, lookup)}
        case t.Buttons():
            items = _links(c.items, lookup)
            return {"items": items} if items else None
        case t.LinkList():
            items = _links(c.items, lookup)
            return {"title": c.title, "items": items} if items else None
        case t.Video():
            provider, vid = t.video_id(c.url) or ("", "")
            return {"title": c.title, "embed_url": tokens.VIDEO_PROVIDERS[provider]["embed_url"].format(id=vid)}
        case t.Details():
            return {"items": [{"question": i.question, "html": _markdown(i.answer, lookup, ())} for i in c.items]}
        case t.Group():
            return {"title": c.title, "landmark": c.landmark}
        case t.Columns():
            return {"count": c.count}
        case t.Empty():  # account·divider
            return {}
    raise NotImplementedError(block_type)
