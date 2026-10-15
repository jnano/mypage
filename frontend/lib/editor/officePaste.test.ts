import { describe, expect, it } from "vitest";
import { isOfficeHtml, tsvToTableHtml } from "./officePaste";

describe("officePaste", () => {
  it("오피스 HTML 표지를 알아본다", () => {
    expect(isOfficeHtml('<p class="MsoNormal">가</p>')).toBe(true);
    expect(isOfficeHtml("<p>가</p>")).toBe(false);
  });

  it("TSV 를 직사각형 표로 바꾸고 이스케이프한다", () => {
    expect(tsvToTableHtml("a\tb\r\nc<\n\n")).toBe("<table><tr><td>a</td><td>b</td></tr><tr><td>c&lt;</td><td></td></tr></table>");
  });

  it("탭이 없거나 한 열이면 표가 아니다", () => {
    expect(tsvToTableHtml("한 줄")).toBeNull();
    expect(tsvToTableHtml("\t")).toBeNull();
    expect(tsvToTableHtml("")).toBeNull();
  });
});
