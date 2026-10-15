"""본문 파이프라인 — 마크다운 변환(§8.4)·nh3 정화(§11)·읽기용 렌더(§4.3)·토큰(§8.2)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.editor import tokens
from app.editor.markdown import MarkdownInputError, markdown_to_html
from app.editor.render import ImageSource, render_content
from app.editor.sanitize import plain_text, sanitize_html

REPO_ROOT = Path(__file__).resolve().parents[2]

# ── 정화 ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # nh3 기본 허용인 lang·title 은 지운다(실측: attributes 를 줘도 남는다 → "*": set())
        ('<p lang="en" title="t">a</p>', "<p>a</p>"),
        ('<p style="color:red" class="x" onclick="y">a</p>', "<p>a</p>"),
        ("<p>a<script>alert(1)</script></p>", "<p>a</p>"),
        ('<iframe src="https://e.com"></iframe><p>a</p>', "<p>a</p>"),
        ('<a href="javascript:alert(1)">x</a>', f'<a rel="{tokens.LINK_REL}">x</a>'),
        ('<a href="/relative">x</a>', f'<a rel="{tokens.LINK_REL}">x</a>'),
        ('<a href="https://e.com" rel="opener" target="_blank">x</a>', f'<a href="https://e.com" rel="{tokens.LINK_REL}">x</a>'),
        ('<a href="mailto:a@b.c">x</a>', f'<a href="mailto:a@b.c" rel="{tokens.LINK_REL}">x</a>'),
        ('<p data-align="middle" data-leading="tight">a</p>', '<p data-leading="tight">a</p>'),
        ('<span data-color="#ff0000">a</span>', "<span>a</span>"),
        ('<figure data-attachment-id="0"><img src="https://e.com/a.png" alt="x"></figure>', '<figure><img alt="x"></figure>'),
        ('<div data-embed="vimeo" data-video-id="short">a</div>', "<div>a</div>"),
        ("<h1>a</h1><h4>b</h4>", "ab"),
        ('<p data-attachment-id="1">a</p>', "<p>a</p>"),  # 다른 태그의 토큰 속성
        ("<!-- c --><p>a</p>", "<p>a</p>"),
    ],
)
def test_sanitize(raw: str, expected: str) -> None:
    assert sanitize_html(raw) == expected


def _every_token_html() -> str:
    """토큰이 허용하는 모든 태그 × 속성 × 값."""
    samples = {"href": "https://example.com/a", "alt": "설명", "data-attachment-id": "12",
               "data-video-id": "dQw4w9WgXcQ", "start": "3", "colspan": "2", "rowspan": "2"}  # fmt: skip
    table_tags = {"table", "thead", "tbody", "tr", "th", "td"}
    flow, cells = [], []
    for tag, attrs in tokens.TAGS.items():
        if tag in table_tags - {"th", "td"}:
            continue  # 표 구조 태그는 아래에서 감싸며 쓴다
        for attr in attrs or ("",):
            rule = tokens.ATTRIBUTE_VALUES.get(attr)
            values = list(rule) if isinstance(rule, tuple) else [samples.get(attr, "")]
            for value in values:
                attr_html = f' {attr}="{value}"' if attr else ""
                if tag == "a":
                    attr_html += f' rel="{tokens.LINK_REL}"'
                html = f"<{tag}{attr_html}>" if tag in ("br", "hr", "img") else f"<{tag}{attr_html}>x</{tag}>"
                (cells if tag in ("th", "td") else flow).append(html)
    table = (
        '<table><thead><tr><th scope="col">x</th></tr></thead>'
        f"<tbody><tr>{''.join(cells)}</tr></tbody></table>"
    )
    return "".join(flow) + table


def test_every_token_survives_sanitizer_unchanged() -> None:
    # 드리프트 검사(§8.7): 에디터가 낼 수 있는 모든 서식이 nh3 를 그대로 통과한다
    html = _every_token_html()
    assert sanitize_html(html) == html


def test_plain_text() -> None:
    assert plain_text("<p>a<strong>b</strong>c</p><p>d &amp; e<br>f</p><ul><li>x</li></ul>") == "abc d & e f x"


# ── 마크다운 ─────────────────────────────────────────────


def test_markdown_headings_are_h2_h3_only() -> None:
    html = markdown_to_html("# 하나\n\n## 둘\n\n### 셋\n\n#### 넷")
    assert html == "<h2>하나</h2>\n<h2>둘</h2>\n<h3>셋</h3>\n<h3>넷</h3>\n"


def test_markdown_raw_html_is_text() -> None:
    assert markdown_to_html("<b>x</b>") == "<p>&lt;b&gt;x&lt;/b&gt;</p>\n"


def test_markdown_link_gets_rel_and_bad_scheme_is_text() -> None:
    html = markdown_to_html("[a](https://e.com) [b](javascript:alert(1))")
    assert f'<a href="https://e.com" rel="{tokens.LINK_REL}">a</a>' in html
    assert "javascript" in html and "href=\"javascript" not in html


@pytest.mark.parametrize(
    "line",
    [
        "https://youtu.be/dQw4w9WgXcQ",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/watch?feature=share&v=dQw4w9WgXcQ&t=10",
        "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ",
        "<https://youtu.be/dQw4w9WgXcQ>",
    ],
)
def test_markdown_video_line(line: str) -> None:
    assert markdown_to_html(line) == '<div data-embed="youtube" data-video-id="dQw4w9WgXcQ"></div>\n'


@pytest.mark.parametrize(
    "text",
    ["영상: https://youtu.be/dQw4w9WgXcQ", "https://vimeo.com/123456", "https://youtu.be/short"],
)
def test_markdown_not_video(text: str) -> None:
    assert "data-embed" not in markdown_to_html(text)


def test_markdown_image_is_figure_without_src() -> None:
    html = markdown_to_html('![회의실 "A"](attachment:12)', {12})
    # 이미지만 있는 문단은 <p> 없이 figure 만 남는다
    assert html == '<figure data-attachment-id="12" data-width="m"><img alt="회의실 &quot;A&quot;"></figure>'


@pytest.mark.parametrize(
    ("source", "allowed"),
    [("![x](https://e.com/a.png)", {12}), ("![x](attachment:5)", {12}), ("![x](attachment:12)", set())],
)
def test_markdown_image_must_be_own_attachment(source: str, allowed: set[int]) -> None:
    with pytest.raises(MarkdownInputError):
        markdown_to_html(source, allowed)


def test_markdown_table_has_scope_and_no_style() -> None:
    html = markdown_to_html("| a | b |\n|:--|--:|\n| 1 | 2 |")
    assert '<th scope="col">a</th>' in html and "style" not in html and "<td>2</td>" in html


# ── 읽기용 렌더 ──────────────────────────────────────────


def test_render_video_iframe_and_image_srcset() -> None:
    html = (
        '<p>a &amp; b</p><figure data-attachment-id="12" data-width="m"><img alt="x"></figure>'
        '<div data-embed="youtube" data-video-id="dQw4w9WgXcQ"></div>'
    )
    out = render_content(html, {12: ImageSource("/media/ab/key", 800, 600, True)})
    assert "<p>a &amp; b</p>" in out
    assert 'src="https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ"' in out
    assert 'srcset="/media/ab/key/thumb?w=320 320w, /media/ab/key/thumb?w=640 640w, /media/ab/key/thumb?w=1280 1280w"' in out
    assert 'width="800" height="600"' in out


def test_render_image_without_thumbs_does_not_expose_original() -> None:
    html = '<figure data-attachment-id="12"><img alt="x"></figure>'
    out = render_content(html, {12: ImageSource("/media/ab/key", 800, 600, False)})
    assert "data-pending" in out and "src=" not in out


def test_render_is_identity_without_tokens() -> None:
    html = "<p>a<br>b</p><hr><ul><li>x</li></ul>"
    assert render_content(html) == html


# ── 토큰 생성 파일(§8.3) ──────────────────────────────────


def test_generated_tokens_file_is_current() -> None:
    res = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "gen_editor_tokens.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stderr
    data = json.loads((REPO_ROOT / "frontend" / "lib" / "editor" / "tokens.gen.json").read_text())
    assert data["sanitizerVersion"] == tokens.SANITIZER_VERSION
