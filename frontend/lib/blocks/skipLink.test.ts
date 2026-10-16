// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { focusVisibleMain, isShown } from "./skipLink";

// 클라이언트 이동 뒤 DOM 모양: 이전 화면은 display:none 상자 안에 남는다(cacheComponents 의 이전 화면 보존)
function page(hiddenFirst: boolean): Document {
  const hidden = '<div style="display: none !important;"><main id="main" data-n="old"></main></div>';
  const shown = '<div><main id="main" data-n="now"></main></div>';
  document.body.innerHTML = '<a href="#main">본문 바로가기</a>' + (hiddenFirst ? hidden + shown : shown + hidden);
  return document;
}

describe("건너뛰기 링크 — 보이는 본문으로", () => {
  it.each([true, false])("숨은 본문이 앞에 있어도(%s) 보이는 본문에 초점", (hiddenFirst) => {
    const doc = page(hiddenFirst);
    expect(focusVisibleMain(doc)).toBe(true);
    expect((doc.activeElement as HTMLElement).dataset.n).toBe("now");
    expect(doc.activeElement?.getAttribute("tabindex")).toBe("-1");
  });

  it("보이는 본문이 없으면 옮기지 않는다(기본 동작에 맡김)", () => {
    document.body.innerHTML = '<div hidden><main id="main"></main></div>';
    expect(focusVisibleMain(document)).toBe(false);
  });

  it("checkVisibility 가 없으면 조상의 숨김을 직접 본다", () => {
    const doc = page(true);
    const [old, now] = [...doc.querySelectorAll<HTMLElement>("main")];
    for (const m of [old, now]) Object.defineProperty(m, "checkVisibility", { value: undefined });
    expect(isShown(old)).toBe(false);
    expect(isShown(now)).toBe(true);
  });
});
