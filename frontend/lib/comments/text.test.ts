import { describe, expect, it } from "vitest";
import { commentSegments } from "./text";

describe("댓글 평문 조각(§8.6)", () => {
  it("줄바꿈·링크·@이름", () => {
    expect(commentSegments("안녕하세요 @가람\n자료는 https://example.com/a?b=1 입니다.")).toEqual([
      { kind: "text", text: "안녕하세요 " },
      { kind: "mention", text: "@가람" },
      { kind: "break" },
      { kind: "text", text: "자료는 " },
      { kind: "link", href: "https://example.com/a?b=1", text: "https://example.com/a?b=1" },
      { kind: "text", text: " 입니다." },
    ]);
  });

  it("문장 끝 부호는 링크에서 뺀다", () => {
    expect(commentSegments("https://example.com.")).toEqual([
      { kind: "link", href: "https://example.com", text: "https://example.com" },
      { kind: "text", text: "." },
    ]);
  });

  it("HTML 은 글자 그대로(링크로 만들지 않는 스킴 포함)", () => {
    expect(commentSegments('<b>x</b> javascript:alert(1) "a"')).toEqual([
      { kind: "text", text: '<b>x</b> javascript:alert(1) "a"' },
    ]);
  });
});
