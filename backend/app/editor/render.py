"""정본 → 읽기용 HTML(content_rendered) — 설계도 §4.3·§8.2.

정본(content_html)은 이미지에 data-attachment-id 만, 동영상에 data-video-id 만 담는다.
여기서 주소·srcset·iframe 을 채워 저장해 두고, 읽기 경로는 파싱 없이 그대로 낸다.
입력은 이미 nh3 를 거친 정본이므로 표준 라이브러리 HTMLParser 로 다시 써도 안전하다.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from html import escape
from html.parser import HTMLParser

from app.editor import tokens

VOID = {"br", "hr", "img"}
THUMB_WIDTHS = (320, 640, 1280)


@dataclass(frozen=True)
class ImageSource:
    """첨부 이미지의 읽기용 주소. 썸네일이 아직 없으면 thumbs_ready=False(자리 표시, 원본 내보내지 않음)."""

    thumb_url: str  # '{w}' 자리를 폭으로 바꾼다 — 공개 /media/ab/<stem>.w{w}.webp, 비공개 /api/attachments/12/thumb?w={w}
    width: int | None
    height: int | None
    thumbs_ready: bool


def _attrs(pairs: list[tuple[str, str | None]]) -> str:
    return "".join(f' {k}="{escape(v or "", quote=True)}"' for k, v in pairs)


class _Renderer(HTMLParser):
    def __init__(self, images: Mapping[int, ImageSource]) -> None:
        super().__init__(convert_charrefs=False)
        self.images = images
        self.out: list[str] = []
        self.figure_id: int | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "figure":
            raw = a.get("data-attachment-id")
            self.figure_id = int(raw) if raw and raw.isdigit() else None
        if tag == "img" and self.figure_id is not None:
            attrs = attrs + self._img_attrs(self.figure_id)
        self.out.append(f"<{tag}{_attrs(attrs)}>")
        if tag == "div" and (provider := tokens.VIDEO_PROVIDERS.get(a.get("data-embed") or "")):
            video_id = a.get("data-video-id") or ""
            src = provider["embed_url"].format(id=video_id)
            self.out.append(
                f'<iframe src="{escape(src, quote=True)}" title="{provider["title"]}"'
                ' loading="lazy" allow="encrypted-media; picture-in-picture; fullscreen"'
                ' referrerpolicy="strict-origin-when-cross-origin" allowfullscreen></iframe>'
            )

    def _img_attrs(self, attachment_id: int) -> list[tuple[str, str | None]]:
        img = self.images.get(attachment_id)
        if img is None:
            return [("data-missing", "")]
        extra: list[tuple[str, str | None]] = []
        if img.width and img.height:
            extra += [("width", str(img.width)), ("height", str(img.height))]
        if not img.thumbs_ready:
            return extra + [("data-pending", "")]
        srcset = ", ".join(f"{img.thumb_url.format(w=w)} {w}w" for w in THUMB_WIDTHS)
        return extra + [
            ("src", img.thumb_url.format(w=640)),
            ("srcset", srcset),
            ("sizes", "(max-width: 640px) 100vw, 640px"),
            ("loading", "lazy"),
            ("decoding", "async"),
        ]

    def handle_endtag(self, tag):
        if tag == "figure":
            self.figure_id = None
        if tag not in VOID:
            self.out.append(f"</{tag}>")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_data(self, data):
        self.out.append(data)

    def handle_entityref(self, name):
        self.out.append(f"&{name};")

    def handle_charref(self, name):
        self.out.append(f"&#{name};")


def render_content(content_html: str, images: Mapping[int, ImageSource] | None = None) -> str:
    r = _Renderer(images or {})
    r.feed(content_html)
    r.close()
    return "".join(r.out)
