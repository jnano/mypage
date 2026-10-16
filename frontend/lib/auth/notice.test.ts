import { describe, expect, it } from "vitest";
import { noticeParagraphs } from "./notice";

describe("고지문 문단", () => {
  it("빈 줄로 나누고 빈 문단은 버린다", () => {
    expect(noticeParagraphs("첫 문단\n이어짐\n\n\n  둘째 문단 \n \n")).toEqual(["첫 문단\n이어짐", "둘째 문단"]);
    expect(noticeParagraphs("")).toEqual([]);
  });
});
