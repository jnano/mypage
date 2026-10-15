// @vitest-environment jsdom
// 리치 에디터 왕복 시험(§8.7) — 저장 HTML → 에디터 → 저장이 그대로인지.
// 같은 fixture 를 백엔드 tests/test_editor.py 가 nh3 에 통과시켜 바뀌지 않는지 본다(드리프트).
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { $generateHtmlFromNodes } from "@lexical/html";
import { createEditor } from "lexical";
import { describe, expect, it } from "vitest";
import { $loadHtml, EDITOR_HTML, EDITOR_NODES } from "@/components/editor/config";

/** fixture 는 블록마다 한 줄 — 블록 사이 줄바꿈만 지운다(코드 블록 안 줄바꿈은 남는다) */
function readFixture(): string {
  // jsdom 환경의 URL 은 file: 를 다루지 않아 경로로 읽는다
  return readFileSync(join(import.meta.dirname, "fixtures/all-formats.html"), "utf8").trim().replace(/>\n</g, "><");
}

function roundTrip(html: string): string {
  const editor = createEditor({
    namespace: "test",
    nodes: EDITOR_NODES,
    html: EDITOR_HTML,
    onError: (e) => {
      throw e;
    },
  });
  editor.update(() => $loadHtml(editor, html), { discrete: true });
  return editor.read(() => $generateHtmlFromNodes(editor, null));
}

describe("리치 에디터 토큰 HTML", () => {
  it("모든 서식이 저장 → 다시 열기 → 저장에서 그대로다", () => {
    const html = readFixture();
    expect(roundTrip(html)).toBe(html);
  });

  it("토큰 밖 꾸밈·속성은 버리고, 제목은 h2·h3 로 맞춘다", () => {
    expect(
      roundTrip('<h1 style="color:red">큰 제목</h1><h5>작은</h5><p class="x" data-align="middle"><span style="font-size:30px" data-color="crimson">글</span></p>'),
    ).toBe("<h2>큰 제목</h2><h3>작은</h3><p>글</p>");
  });

  it("그림은 첨부 id 가 있어야 하고 src 를 저장하지 않는다", () => {
    expect(roundTrip('<p>앞</p><figure data-attachment-id="5"><img src="https://e.com/a.png" alt="가"></figure><p><img src="https://e.com/b.png"></p>')).toBe(
      '<p>앞</p><figure data-attachment-id="5" data-width="m"><img alt="가"></figure><p></p>',
    );
  });
});
